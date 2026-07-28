#include "modes/gait/rr_akr.h"

#include "runtime/app_config.h"
#include "devices/icm20948.h"
#include "modes/gait/model_tools.h"
#include "modes/gait/model_test.h"
#include "modes/gait/model_update.h"
#include "actuators/robstride.h"
#include "modes/passive/rr_passive.h"
#include "modes/rr_persist.h"
#include "sensing/battery.h"
#include "telem/rr_telem.h"
#include "ui/buzzer.h"
#include "runtime/robot_role.h"
#include <math.h>
#include <string.h>

Signal g_rr_akr_sig;
Model g_rr_akr_gait;
uint32_t g_rr_akr_last_ms = 0;
bool g_rr_akr_inited = false;
static bool s_rr_akr_imu_ok = false;
static uint32_t s_rr_akr_last_imu_update_ms = 0U;
static ModelOutput s_rr_akr_last_out = MODEL_OUTPUT_RELEASE;
static RR_AKR_GaitModel s_rr_akr_gait_model = (RR_AKR_GaitModel)APP_CFG_AKR_DEFAULT_GAIT_MODEL;
static RR_AKR_MoveParams s_rr_akr_df_params;
static RR_AKR_MoveParams s_rr_akr_pf_params;
static RR_AKR_MoveParams s_rr_akr_neutral_params;
static float s_rr_akr_assist_pct = APP_CFG_AKR_DEFAULT_ASSIST_PCT;
static ModelState s_rr_akr_fade_last_state = MODEL_FAILSAFE;
static float s_rr_akr_fade_ref_abs_gyr_z_dps = 0.0f;
static bool s_rr_akr_fade_ref_valid = false;
static float s_rr_akr_fade_last_ratio = 0.0f;

typedef struct
{
  uint8_t gait_model;
  uint8_t gait_mode;
  uint8_t side_is_left;
  float assist_pct;
  RR_AKR_MoveParams df;
  RR_AKR_MoveParams pf;
  RR_AKR_MoveParams neutral;
  RR_Passive_CpmParams cpm;
} RR_AKR_TelemCfgSnapshot;

static uint32_t s_rr_akr_fast_telem_fid = 0U;
static uint32_t s_rr_akr_cfg_telem_fid = 0U;
static uint32_t s_rr_akr_cfg_last_ms = 0U;
static bool s_rr_akr_cfg_has_last = false;
static RR_AKR_TelemCfgSnapshot s_rr_akr_cfg_last = {0};
static uint32_t s_rr_akr_effective_step_count = 0U;
static bool s_rr_akr_effective_step_active = false;
static RR_AKR_WalkSample s_rr_akr_latest_walk_sample = {0};

typedef struct
{
  void (*init)(Model *m);
  void (*set_mode)(Model *m, ModelMode mode);
  void (*update_signal)(Model *m, const Signal *sig);
  ModelState (*event_detection)(Model *m, float dt_us);
  ModelOutput (*action)(const Model *m);
} RR_AKR_ModelOps;

/* Private helper prototypes (internal linkage only). */
static float s_rr_akr_clamp01f(float x);
static float s_rr_akr_mid_swing_exit_neg_mag_dps(void);
static const RR_AKR_ModelOps *s_rr_akr_get_model_ops(RR_AKR_GaitModel gait_model);
static void s_rr_akr_model_reset_state(void);
static void s_rr_akr_fade_reset(void);
static void s_rr_akr_fade_update_reference(void);
static float s_rr_akr_fade_ratio(void);
static float s_rr_akr_push_off_gain_ratio(void);
static void s_rr_akr_telemetry_fill_cfg_snapshot(RR_AKR_TelemCfgSnapshot *snap);
static bool s_rr_akr_telemetry_cfg_changed(const RR_AKR_TelemCfgSnapshot *a, const RR_AKR_TelemCfgSnapshot *b);
static void s_rr_akr_telemetry_cfg_step(uint32_t now_ms);
static void s_rr_akr_telemetry_step(ModelOutput out, uint32_t dt_ms, uint16_t exec_ms);
static void s_rr_akr_reset_effective_step_count(void);
static float s_rr_akr_side_sign(void);
static void s_rr_akr_command_move(float torque, float angle, float speed, float kp, float kd);
static void s_rr_akr_command_stop(void);
static void RR_AKR_Step(uint32_t dt_ms);

/* Private helpers */
static const RR_AKR_ModelOps *s_rr_akr_get_model_ops(RR_AKR_GaitModel gait_model)
{
  static const RR_AKR_ModelOps s_rr_akr_model_ops_update = {
    ModelTools_Init,
    ModelTools_SetMode,
    ModelTools_UpdateSignal,
    ModelUpdate_EventDetection,
    ModelUpdate_Action
  };
  static const RR_AKR_ModelOps s_rr_akr_model_ops_test = {
    ModelTools_Init,
    ModelTools_SetMode,
    ModelTools_UpdateSignal,
    ModelTest_EventDetection,
    ModelTest_Action
  };

  switch(gait_model)
  {
    case RR_AKR_GAIT_MODEL_UPDATE:
      return &s_rr_akr_model_ops_update;
    case RR_AKR_GAIT_MODEL_TEST:
      return &s_rr_akr_model_ops_test;
    default:
      return NULL;
  }
}

static void s_rr_akr_model_reset_state(void)
{
  const RR_AKR_ModelOps *model_ops = s_rr_akr_get_model_ops(s_rr_akr_gait_model);
  if(model_ops == NULL)
  {
    return;
  }
  model_ops->init(&g_rr_akr_gait);
  model_ops->set_mode(&g_rr_akr_gait, MODEL_LEVEL_WALK);
}

static float s_rr_akr_clamp01f(float x)
{
  if(x < 0.0f)
  {
    return 0.0f;
  }
  if(x > 1.0f)
  {
    return 1.0f;
  }
  return x;
}

static float s_rr_akr_mid_swing_exit_neg_mag_dps(void)
{
  float threshold_dps = APP_CFG_MODEL_MID_SWING_POS_GYRO_MIN_DPS;

  if(g_rr_akr_gait.mode == MODEL_STAIR_UP)
  {
    threshold_dps = APP_CFG_MODEL_STAIR_UP_MID_SWING_POS_GYRO_MIN_DPS;
  }

  return (threshold_dps < 0.0f) ? (-threshold_dps) : 0.0f;
}

static void s_rr_akr_fade_reset(void)
{
  s_rr_akr_fade_last_state = g_rr_akr_gait.state;
  s_rr_akr_fade_ref_abs_gyr_z_dps = 0.0f;
  s_rr_akr_fade_ref_valid = false;
  s_rr_akr_fade_last_ratio = 0.0f;
}

static void s_rr_akr_fade_update_reference(void)
{
  /* Fade reference management:
   * 1) On MID_SWING entry, latch |gyro_z| as the fade reference.
   * 2) Re-arm monotonic fade tracking at MID_SWING entry.
   * 3) While outside MID_SWING, clear all fade state so stale values are never reused.
   * 4) Keep the previous state to detect the exact state transition edge.
   */
  if((g_rr_akr_gait.state == MODEL_MID_SWING) && (s_rr_akr_fade_last_state != MODEL_MID_SWING))
  {
    const float gyr_z = g_rr_akr_gait.gyro[0];
    s_rr_akr_fade_ref_abs_gyr_z_dps = fabsf(gyr_z);
    s_rr_akr_fade_ref_valid = (s_rr_akr_fade_ref_abs_gyr_z_dps > 1e-6f);
    s_rr_akr_fade_last_ratio = 1.0f;
  }
  else if((g_rr_akr_gait.state != MODEL_MID_SWING) && (s_rr_akr_fade_last_state == MODEL_MID_SWING))
  {
    s_rr_akr_fade_ref_abs_gyr_z_dps = 0.0f;
    s_rr_akr_fade_ref_valid = false;
    s_rr_akr_fade_last_ratio = 0.0f;
  }

  s_rr_akr_fade_last_state = g_rr_akr_gait.state;
}

static float s_rr_akr_fade_ratio(void)
{
  float inst_ratio = 0.0f;
  float neg_mag = 0.0f;
  const float exit_neg_mag_dps = s_rr_akr_mid_swing_exit_neg_mag_dps();
  const float fade_span_dps = s_rr_akr_fade_ref_abs_gyr_z_dps - exit_neg_mag_dps;

  if(!s_rr_akr_fade_ref_valid)
  {
    return 0.0f;
  }
  if(g_rr_akr_gait.state != MODEL_MID_SWING)
  {
    return 0.0f;
  }
  if(s_rr_akr_fade_ref_abs_gyr_z_dps <= 1e-9f)
  {
    return 0.0f;
  }
  if(fade_span_dps <= 1e-9f)
  {
    s_rr_akr_fade_last_ratio = 0.0f;
    return 0.0f;
  }

  /* In MID_SWING, fade gain tracks the active negative gyro range:
   * 1) only the negative gyro magnitude contributes,
   * 2) the configured state-exit threshold is the zero-gain endpoint,
   * 3) the latched entry reference is the full-gain endpoint,
   * 4) clamp the normalized result for stable Kp/Kd scaling.
   */
  if(g_rr_akr_gait.gyro[0] < 0.0f)
  {
    neg_mag = -g_rr_akr_gait.gyro[0];
  }
  if(neg_mag <= exit_neg_mag_dps)
  {
    s_rr_akr_fade_last_ratio = 0.0f;
    return 0.0f;
  }
  inst_ratio = s_rr_akr_clamp01f((float)((neg_mag - exit_neg_mag_dps) / fade_span_dps));

  /* Keep fade outputs strictly one-way during MID_SWING:
   * - first frame starts from 1.0 (set on entry),
   * - each frame applies min(instantaneous, previous),
   * - once it reaches 0, it cannot rebound until next MID_SWING entry.
   */
  if(inst_ratio > s_rr_akr_fade_last_ratio)
  {
    inst_ratio = s_rr_akr_fade_last_ratio;
  }
  s_rr_akr_fade_last_ratio = inst_ratio;
  return inst_ratio;
}

static float s_rr_akr_push_off_gain_ratio(void)
{
  const float tilt_deg = (float)g_rr_akr_sig.tilt_forward.lp[0];
  const float tilt_min = APP_CFG_MODEL_PUSH_OFF_TILT_MIN_DEG;
  const float tilt_max = APP_CFG_MODEL_PUSH_OFF_TILT_MAX_DEG;
  float gain_min = APP_CFG_MODEL_PUSH_OFF_GAIN_MIN;
  float gain_max = APP_CFG_MODEL_PUSH_OFF_GAIN_MAX;
  float tilt_norm = 0.0f;

  /* Push-off gain map:
   * 1) take only forward tilt (negative/near-zero tilt should not add push-off),
   * 2) normalize linearly in [tilt_min, tilt_max],
   * 3) map to [gain_min, gain_max] and clamp for stable Kp/Kd scaling.
   */
  if(gain_min > gain_max)
  {
    const float tmp = gain_min;
    gain_min = gain_max;
    gain_max = tmp;
  }
  if(tilt_max > tilt_min)
  {
    tilt_norm = (tilt_deg - tilt_min) / (tilt_max - tilt_min);
  }
  tilt_norm = s_rr_akr_clamp01f(tilt_norm);
  return gain_min + ((gain_max - gain_min) * tilt_norm);
}

static void s_rr_akr_telemetry_fill_cfg_snapshot(RR_AKR_TelemCfgSnapshot *snap)
{
  if(snap == NULL)
  {
    return;
  }
  snap->gait_model = (uint8_t)RR_AKR_GetGaitModel();
  snap->gait_mode = (uint8_t)RR_AKR_GetWalkMode();
  snap->side_is_left = Signal_IsLeft() ? 1U : 0U;
  snap->assist_pct = s_rr_akr_assist_pct;
  snap->df = s_rr_akr_df_params;
  snap->pf = s_rr_akr_pf_params;
  snap->neutral = s_rr_akr_neutral_params;
  snap->cpm = RR_Passive_CpmGetParams();
}

static bool s_rr_akr_telemetry_cfg_changed(const RR_AKR_TelemCfgSnapshot *a,
                                           const RR_AKR_TelemCfgSnapshot *b)
{
  if((a == NULL) || (b == NULL))
  {
    return true;
  }

  /* Config frame is event-driven:
   * - emit immediately when any AKR tuning/side item changes
   * - fall back to periodic keepalive in the step loop
   */
  return (a->side_is_left != b->side_is_left) ||
         (a->gait_model != b->gait_model) ||
         (a->gait_mode != b->gait_mode) ||
         (a->assist_pct != b->assist_pct) ||
         (a->df.torque != b->df.torque) ||
         (a->df.angle != b->df.angle) ||
         (a->df.speed != b->df.speed) ||
         (a->df.kp != b->df.kp) ||
         (a->df.kd != b->df.kd) ||
         (a->pf.torque != b->pf.torque) ||
         (a->pf.angle != b->pf.angle) ||
         (a->pf.speed != b->pf.speed) ||
         (a->pf.kp != b->pf.kp) ||
         (a->pf.kd != b->pf.kd) ||
         (a->neutral.torque != b->neutral.torque) ||
         (a->neutral.angle != b->neutral.angle) ||
         (a->neutral.speed != b->neutral.speed) ||
         (a->neutral.kp != b->neutral.kp) ||
         (a->neutral.kd != b->neutral.kd) ||
         (a->cpm.target_df_rad != b->cpm.target_df_rad) ||
         (a->cpm.target_pf_rad != b->cpm.target_pf_rad) ||
         (a->cpm.speed_to_df_rad_s != b->cpm.speed_to_df_rad_s) ||
         (a->cpm.speed_to_pf_rad_s != b->cpm.speed_to_pf_rad_s) ||
         (a->cpm.block_torque_thresh != b->cpm.block_torque_thresh) ||
         (a->cpm.wait_to_df_ms != b->cpm.wait_to_df_ms) ||
         (a->cpm.wait_to_pf_ms != b->cpm.wait_to_pf_ms);
}

static void s_rr_akr_telemetry_cfg_step(uint32_t now_ms)
{
  RR_AKR_TelemCfgSnapshot cfg_now = {0};
  const bool cfg_due = ((uint32_t)(now_ms - s_rr_akr_cfg_last_ms) >= APP_CFG_TELEM_CFG_KEEPALIVE_MS);
  bool cfg_changed = false;

  s_rr_akr_telemetry_fill_cfg_snapshot(&cfg_now);
  cfg_changed = (!s_rr_akr_cfg_has_last) || s_rr_akr_telemetry_cfg_changed(&cfg_now, &s_rr_akr_cfg_last);
  if(cfg_due || cfg_changed)
  {
    RR_Telem_SendCfg(s_rr_akr_cfg_telem_fid++,
                     cfg_now.gait_model,
                     cfg_now.gait_mode,
                     cfg_now.side_is_left,
                     cfg_now.assist_pct,
                     cfg_now.df.torque,
                     cfg_now.df.angle,
                     cfg_now.df.speed,
                     cfg_now.df.kp,
                     cfg_now.df.kd,
                     cfg_now.pf.torque,
                     cfg_now.pf.angle,
                     cfg_now.pf.speed,
                     cfg_now.pf.kp,
                     cfg_now.pf.kd,
                     cfg_now.neutral.torque,
                     cfg_now.neutral.angle,
                     cfg_now.neutral.speed,
                     cfg_now.neutral.kp,
                     cfg_now.neutral.kd,
                     cfg_now.cpm.target_df_rad,
                     cfg_now.cpm.target_pf_rad,
                     cfg_now.cpm.speed_to_df_rad_s,
                     cfg_now.cpm.speed_to_pf_rad_s,
                     cfg_now.cpm.block_torque_thresh,
                     cfg_now.cpm.wait_to_df_ms,
                     cfg_now.cpm.wait_to_pf_ms);
    s_rr_akr_cfg_last = cfg_now;
    s_rr_akr_cfg_last_ms = now_ms;
    s_rr_akr_cfg_has_last = true;
  }
}

static void s_rr_akr_telemetry_step(ModelOutput out, uint32_t dt_ms, uint16_t exec_ms)
{
  const uint32_t now_ms = HAL_GetTick();
  const uint32_t age = (g_robstride_motor_last_feedback_ms == 0U) ? 0xFFFFFFFFU :
                       (uint32_t)(now_ms - g_robstride_motor_last_feedback_ms);
  const uint16_t age_u16 = (age > 0xFFFFU) ? 0xFFFFU : (uint16_t)age;
  const float typical_stride_ms = (float)ModelTools_StrideGuardGetEstimatedTypicalStrideMs();
  const float effective_step_count = (float)s_rr_akr_effective_step_count;
  const float tilt_acc_only_deg = (float)ModelTools_ForwardTiltAccOnlyDeg(&g_rr_akr_sig);
  const BatterySnapshot battery = Battery_GetSnapshot();
  const uint8_t battery_soc_pct = (battery.valid != 0U) ? battery.soc_pct : 0U;
  float vbus_v = 0.0f;

  (void)RS_VBus_GetCached(&vbus_v, NULL);
  RR_Telem_SendAKR(s_rr_akr_fast_telem_fid++,
                   (uint16_t)dt_ms,
                   exec_ms,
                   (int8_t)out,
                   (int8_t)g_rr_akr_gait.state,
                   (float)g_rr_akr_sig.acc.x.lp[0],
                   (float)g_rr_akr_sig.acc.y.lp[0],
                   (float)g_rr_akr_sig.acc.z.lp[0],
                   (float)g_rr_akr_sig.gyro.x.lp[0],
                   (float)g_rr_akr_sig.gyro.y.lp[0],
                   (float)g_rr_akr_sig.gyro.z.lp[0],
                   (float)typical_stride_ms,
                   (float)effective_step_count,
                   (float)tilt_acc_only_deg,
                   (float)g_rr_akr_sig.tilt_forward.lp[0],
                   g_robstride_motor.Pos_Info.Angle,
                   g_robstride_motor.Pos_Info.Speed,
                   g_robstride_motor.Pos_Info.Torque,
                   g_robstride_motor.Pos_Info.Temp,
                   vbus_v,
                   battery_soc_pct,
                   RS_GetTelemetryErrorCode(),
                   age_u16);

  s_rr_akr_telemetry_cfg_step(now_ms);
}

static void s_rr_akr_reset_effective_step_count(void)
{
  s_rr_akr_effective_step_count = 0U;
  s_rr_akr_effective_step_active = false;
}

static float s_rr_akr_side_sign(void)
{
  return Signal_IsLeft() ? -1.0f : 1.0f;
}

static void s_rr_akr_command_move(float torque, float angle, float speed, float kp, float kd)
{
  RobStride_Motor_move_control(torque, angle, speed, kp, kd);
}

static void s_rr_akr_command_stop(void)
{
  Disenable_Motor(0U);
}

void RR_AKR_ResetMoveParamsDefaults(void)
{
  const AppCfgAkrDefaults *cfg = AppConfig_GetAkrDefaults();

  s_rr_akr_df_params.torque = cfg->df.torque;
  s_rr_akr_df_params.angle = cfg->df.angle;
  s_rr_akr_df_params.speed = cfg->df.speed;
  s_rr_akr_df_params.kp = cfg->df.kp;
  s_rr_akr_df_params.kd = cfg->df.kd;

  s_rr_akr_pf_params.torque = cfg->pf.torque;
  s_rr_akr_pf_params.angle = cfg->pf.angle;
  s_rr_akr_pf_params.speed = cfg->pf.speed;
  s_rr_akr_pf_params.kp = cfg->pf.kp;
  s_rr_akr_pf_params.kd = cfg->pf.kd;

  s_rr_akr_neutral_params.torque = cfg->neutral.torque;
  s_rr_akr_neutral_params.angle = cfg->neutral.angle;
  s_rr_akr_neutral_params.speed = cfg->neutral.speed;
  s_rr_akr_neutral_params.kp = cfg->neutral.kp;
  s_rr_akr_neutral_params.kd = cfg->neutral.kd;

  s_rr_akr_assist_pct = APP_CFG_AKR_DEFAULT_ASSIST_PCT;
}

/* Public API */
bool RR_AKR_GetMoveParams(ModelOutput out, RR_AKR_MoveParams *params_out)
{
  if(params_out == NULL)
  {
    return false;
  }

  if((out == MODEL_OUTPUT_DF) || (out == MODEL_OUTPUT_DF_FADE))
  {
    *params_out = s_rr_akr_df_params;
    return true;
  }
  if((out == MODEL_OUTPUT_PF) ||
     (out == MODEL_OUTPUT_PF_FADE) ||
     (out == MODEL_OUTPUT_PUSH_OFF))
  {
    *params_out = s_rr_akr_pf_params;
    return true;
  }
  if(out == MODEL_OUTPUT_NEUTRAL)
  {
    *params_out = s_rr_akr_neutral_params;
    return true;
  }
  return false;
}

bool RR_AKR_SetMoveParams(ModelOutput out, const RR_AKR_MoveParams *params)
{
  if(params == NULL)
  {
    return false;
  }

  if((out == MODEL_OUTPUT_DF) || (out == MODEL_OUTPUT_DF_FADE))
  {
    s_rr_akr_df_params = *params;
    return true;
  }
  if((out == MODEL_OUTPUT_PF) ||
     (out == MODEL_OUTPUT_PF_FADE) ||
     (out == MODEL_OUTPUT_PUSH_OFF))
  {
    s_rr_akr_pf_params = *params;
    return true;
  }
  if(out == MODEL_OUTPUT_NEUTRAL)
  {
    s_rr_akr_neutral_params = *params;
    return true;
  }
  return false;
}

void RR_AKR_ApplyModelOutput(ModelOutput out, bool force)
{
  const float side_sign = s_rr_akr_side_sign();
  float kp = 0.0f;
  float kd = 0.0f;
  const float assist_scale = s_rr_akr_assist_pct * 0.01f;

  // Fade and PUSH_OFF outputs are refreshed each cycle because gain scaling is dynamic.
  if((!force) &&
     (out == s_rr_akr_last_out) &&
     (out != MODEL_OUTPUT_DF_FADE) &&
     (out != MODEL_OUTPUT_PF_FADE) &&
     (out != MODEL_OUTPUT_PUSH_OFF))
  {
    return;
  }

  switch(out)
  {
    case MODEL_OUTPUT_DF:
      kp = s_rr_akr_df_params.kp * assist_scale;
      kd = s_rr_akr_df_params.kd * assist_scale;
      s_rr_akr_command_move(s_rr_akr_df_params.torque * side_sign,
                            s_rr_akr_df_params.angle * side_sign,
                            s_rr_akr_df_params.speed * side_sign,
                            kp,
                            kd);
      break;
    case MODEL_OUTPUT_DF_FADE:
    {
      const float fade_ratio = s_rr_akr_fade_ratio();
      if(fade_ratio <= 0.0f)
      {
        s_rr_akr_command_stop();
        break;
      }
      kp = s_rr_akr_df_params.kp * assist_scale * fade_ratio;
      kd = s_rr_akr_df_params.kd * assist_scale * fade_ratio;
      s_rr_akr_command_move(s_rr_akr_df_params.torque * side_sign,
                            s_rr_akr_df_params.angle * side_sign,
                            s_rr_akr_df_params.speed * side_sign,
                            kp,
                            kd);
      break;
    }
    case MODEL_OUTPUT_PF:
      kp = s_rr_akr_pf_params.kp * assist_scale;
      kd = s_rr_akr_pf_params.kd * assist_scale;
      s_rr_akr_command_move(s_rr_akr_pf_params.torque * side_sign,
                            s_rr_akr_pf_params.angle * side_sign,
                            s_rr_akr_pf_params.speed * side_sign,
                            kp,
                            kd);
      break;
    case MODEL_OUTPUT_PF_FADE:
    {
      const float fade_ratio = s_rr_akr_fade_ratio();
      if(fade_ratio <= 0.0f)
      {
        s_rr_akr_command_stop();
        break;
      }
      kp = s_rr_akr_pf_params.kp * assist_scale * fade_ratio;
      kd = s_rr_akr_pf_params.kd * assist_scale * fade_ratio;
      s_rr_akr_command_move(s_rr_akr_pf_params.torque * side_sign,
                            s_rr_akr_pf_params.angle * side_sign,
                            s_rr_akr_pf_params.speed * side_sign,
                            kp,
                            kd);
      break;
    }
    case MODEL_OUTPUT_PUSH_OFF:
    {
      const float push_off_ratio = s_rr_akr_push_off_gain_ratio();
      kp = s_rr_akr_pf_params.kp * assist_scale * push_off_ratio;
      kd = s_rr_akr_pf_params.kd * assist_scale * push_off_ratio;
      s_rr_akr_command_move(s_rr_akr_pf_params.torque * side_sign,
                            s_rr_akr_pf_params.angle * side_sign,
                            s_rr_akr_pf_params.speed * side_sign,
                            kp,
                            kd);
      break;
    }
    case MODEL_OUTPUT_NEUTRAL:
      kp = s_rr_akr_neutral_params.kp * assist_scale;
      kd = s_rr_akr_neutral_params.kd * assist_scale;
      s_rr_akr_command_move(s_rr_akr_neutral_params.torque * side_sign,
                            s_rr_akr_neutral_params.angle * side_sign,
                            s_rr_akr_neutral_params.speed * side_sign,
                            kp,
                            kd);
      break;
    case MODEL_OUTPUT_RELEASE:
    default:
      s_rr_akr_command_stop();
      break;
  }

  s_rr_akr_last_out = out;
}

void RR_AKR_Init(void)
{
  const AppCfgAkrDefaults *cfg = AppConfig_GetAkrDefaults();
  const RR_AKR_GaitModel gait_model = RR_AKR_GetRequiredGaitModel();
  uint8_t is_left = 0U;
  const float sample_dt_us = (float)RR_AKR_LOOP_PERIOD_MS * 1000.0f;
  const RR_AKR_ModelOps *model_ops = NULL;
  if(!RR_AKR_SetGaitModel(gait_model))
  {
    s_rr_akr_gait_model = (RR_AKR_GaitModel)APP_CFG_AKR_DEFAULT_GAIT_MODEL;
  }
  model_ops = s_rr_akr_get_model_ops(s_rr_akr_gait_model);
  if(model_ops == NULL)
  {
    return;
  }
  s_rr_akr_imu_ok = (ICM20948_Init() == 0U);

  Signal_SetIsLeft(cfg->is_left);
  Signal_Init(&g_rr_akr_sig, sample_dt_us, cfg->signal_lowpass_hz, cfg->signal_highpass_hz);

  model_ops->init(&g_rr_akr_gait);
  model_ops->set_mode(&g_rr_akr_gait, MODEL_LEVEL_WALK);
  RR_AKR_ResetMoveParamsDefaults();

  if(RR_Persist_LoadAkr(&s_rr_akr_df_params,
                        &s_rr_akr_pf_params,
                        &s_rr_akr_neutral_params,
                        &is_left,
                        &s_rr_akr_assist_pct))
  {
    Signal_SetIsLeft(is_left != 0U);
  }

  s_rr_akr_last_out = MODEL_OUTPUT_RELEASE;
  s_rr_akr_last_imu_update_ms = HAL_GetTick();
  s_rr_akr_fade_reset();
  s_rr_akr_reset_effective_step_count();
  (void)memset(&s_rr_akr_latest_walk_sample, 0, sizeof(s_rr_akr_latest_walk_sample));
  g_rr_akr_last_ms = HAL_GetTick();
  g_rr_akr_inited = true;
}

void RR_AKR_ModeEnter(void)
{
  s_rr_akr_command_stop();

  g_rr_akr_last_ms = HAL_GetTick();
  s_rr_akr_model_reset_state();
  s_rr_akr_last_out = MODEL_OUTPUT_RELEASE;
  s_rr_akr_fade_reset();
  s_rr_akr_reset_effective_step_count();

}

void RR_AKR_ModeExit(void)
{
  s_rr_akr_command_stop();
}

static void RR_AKR_Step(uint32_t dt_ms)
{
  const uint32_t step_start_ms = HAL_GetTick();
  const float dt_us = (float)dt_ms * 1000.0f;
  const RR_AKR_ModelOps *model_ops = s_rr_akr_get_model_ops(s_rr_akr_gait_model);
  ModelOutput out = MODEL_OUTPUT_RELEASE;
  if(model_ops == NULL)
  {
    return;
  }

  Signal_Update(&g_rr_akr_sig, dt_us);
  RR_AKR_NotifyImuUpdated(step_start_ms);

  model_ops->update_signal(&g_rr_akr_gait, &g_rr_akr_sig);
  (void)model_ops->event_detection(&g_rr_akr_gait, dt_us);
  s_rr_akr_fade_update_reference();
  out = model_ops->action(&g_rr_akr_gait);
  RR_AKR_ApplyModelOutput(out, false);
  /* Publish exactly one immutable debug sample after each complete gait update.
   * The sequence changes last so a polling link consumer never sees a new
   * sequence paired with partially updated sample fields. */
  s_rr_akr_latest_walk_sample.timestamp_ms = step_start_ms;
  s_rr_akr_latest_walk_sample.gyro_z_dps = (float)g_rr_akr_gait.gyro[0];
  s_rr_akr_latest_walk_sample.tilt_forward_deg = (float)g_rr_akr_sig.tilt_forward.lp[0];
  s_rr_akr_latest_walk_sample.gait_state = (uint8_t)g_rr_akr_gait.state;
  s_rr_akr_latest_walk_sample.terrain = (uint8_t)g_rr_akr_gait.mode;
  s_rr_akr_latest_walk_sample.sequence++;
  /* Effective-step flow:
   * 1) treat assist outputs as an active step phase; NEUTRAL is stance hold,
   * 2) count/beep only on the rising edge so one step yields one cue,
   * 3) skip cue while buzzer is busy so warning/OTA/fault audio is not interrupted.
   */
  if((out != MODEL_OUTPUT_RELEASE) && (out != MODEL_OUTPUT_NEUTRAL))
  {
    if(!s_rr_akr_effective_step_active)
    {
      s_rr_akr_effective_step_count++;
      s_rr_akr_effective_step_active = true;
      if(!BUZZER_IsBusy())
      {
        BUZZER_PlayPresetNonCritical(BUZZER_PRESET_OK);
      }
    }
  }
  else
  {
    s_rr_akr_effective_step_active = false;
  }

  // Keep AKR telemetry lightweight: frame ids are not persisted across reboot.
  {
    const uint32_t exec_elapsed_ms = HAL_GetTick() - step_start_ms;
    const uint16_t exec_u16 = (exec_elapsed_ms > 0xFFFFU) ? 0xFFFFU : (uint16_t)exec_elapsed_ms;
    s_rr_akr_telemetry_step(out, dt_ms, exec_u16);
  }
}

void RR_AKR_Loop(void)
{
  if(g_rr_akr_inited)
  {
    const uint32_t now = HAL_GetTick();
    const uint32_t elapsed = now - g_rr_akr_last_ms;
    if(elapsed >= RR_AKR_LOOP_PERIOD_MS)
    {
      g_rr_akr_last_ms = now;
      RR_AKR_Step(elapsed);
    }
  }
}

bool RR_AKR_LoadMoveParams(void)
{
  uint8_t is_left = Signal_IsLeft() ? 1U : 0U;
  if(!RR_Persist_LoadAkr(&s_rr_akr_df_params,
                         &s_rr_akr_pf_params,
                         &s_rr_akr_neutral_params,
                         &is_left,
                         &s_rr_akr_assist_pct))
  {
    return false;
  }
  Signal_SetIsLeft(is_left != 0U);
  return true;
}

bool RR_AKR_SaveMoveParams(void)
{
  return RR_Persist_SaveAkr(&s_rr_akr_df_params,
                            &s_rr_akr_pf_params,
                            &s_rr_akr_neutral_params,
                            Signal_IsLeft() ? 1U : 0U,
                            s_rr_akr_assist_pct);
}

bool RR_AKR_SetAssistLevelPct(float assist_pct)
{
  if(assist_pct < 0.0f)
  {
    assist_pct = 0.0f;
  }
  if(assist_pct > 100.0f)
  {
    assist_pct = 100.0f;
  }

  s_rr_akr_assist_pct = assist_pct;
  return true;
}

bool RR_AKR_GetAssistLevelPct(float *assist_pct_out)
{
  if(assist_pct_out == NULL)
  {
    return false;
  }
  *assist_pct_out = s_rr_akr_assist_pct;
  return true;
}

bool RR_AKR_IsImuOk(void)
{
  return s_rr_akr_imu_ok;
}

void RR_AKR_NotifyImuUpdated(uint32_t now_ms)
{
  s_rr_akr_last_imu_update_ms = now_ms;
}

uint32_t RR_AKR_GetLastImuUpdateMs(void)
{
  return s_rr_akr_last_imu_update_ms;
}

uint32_t RR_AKR_GetLastStepMs(void)
{
  return g_rr_akr_last_ms;
}

bool RR_AKR_SetWalkMode(ModelMode walk_mode)
{
  const RR_AKR_ModelOps *model_ops = s_rr_akr_get_model_ops(s_rr_akr_gait_model);
  const int mode_i = (int)walk_mode;
  const ModelMode prev_mode = g_rr_akr_gait.mode;
  if(model_ops == NULL)
  {
    return false;
  }
  if((mode_i < 0) || (mode_i >= MODEL_MODE_END))
  {
    return false;
  }
  model_ops->set_mode(&g_rr_akr_gait, walk_mode);
  if(prev_mode != walk_mode)
  {
    s_rr_akr_reset_effective_step_count();
  }
  return true;
}

ModelMode RR_AKR_GetWalkMode(void)
{
  return g_rr_akr_gait.mode;
}

ModelOutput RR_AKR_GetLastOutput(void)
{
  return s_rr_akr_last_out;
}

bool RR_AKR_SetGaitModel(RR_AKR_GaitModel gait_model)
{
  if((s_rr_akr_get_model_ops(gait_model) == NULL) ||
     (gait_model != RR_AKR_GetRequiredGaitModel()))
  {
    return false;
  }
  s_rr_akr_command_stop();
  s_rr_akr_gait_model = gait_model;
  s_rr_akr_model_reset_state();
  s_rr_akr_last_out = MODEL_OUTPUT_RELEASE;
  s_rr_akr_fade_reset();
  return true;
}

bool RR_AKR_SetGaitModelByName(const char *name)
{
  if(name == NULL)
  {
    return false;
  }
  if(strcmp(name, "update") == 0)
  {
    return RR_AKR_SetGaitModel(RR_AKR_GAIT_MODEL_UPDATE);
  }
  if(strcmp(name, "test") == 0)
  {
    return RR_AKR_SetGaitModel(RR_AKR_GAIT_MODEL_TEST);
  }
  return false;
}

RR_AKR_GaitModel RR_AKR_GetGaitModel(void)
{
  return s_rr_akr_gait_model;
}

const char *RR_AKR_GetGaitModelName(void)
{
  switch(s_rr_akr_gait_model)
  {
    case RR_AKR_GAIT_MODEL_UPDATE:
      return "update";
    case RR_AKR_GAIT_MODEL_TEST:
      return "test";
    default:
      return "unknown";
  }
}

RR_AKR_GaitModel RR_AKR_GetRequiredGaitModel(void)
{
  return RobotRole_IsConsole() ? RR_AKR_GAIT_MODEL_UPDATE : RR_AKR_GAIT_MODEL_TEST;
}

bool RR_AKR_GetLatestWalkSample(RR_AKR_WalkSample *sample_out)
{
  if((sample_out == NULL) || (s_rr_akr_latest_walk_sample.sequence == 0U))
  {
    return false;
  }
  *sample_out = s_rr_akr_latest_walk_sample;
  return true;
}
