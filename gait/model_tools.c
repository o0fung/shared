#include "modes/gait/model_tools.h"

#include <math.h>

static bool s_model_tools_tilt_failsafe_enabled = APP_CFG_MODEL_TILT_FAILSAFE_ENABLE;
static bool s_model_tools_level_push_off_release_enabled = APP_CFG_MODEL_LEVEL_PUSH_OFF_RELEASE_ENABLE;
static bool s_model_tools_level_stance_neutral_enabled = APP_CFG_MODEL_LEVEL_STANCE_NEUTRAL_ENABLE;

/* Stride guard (plain-language intent):
 * - We only trust assistance when steps arrive with a walk-like rhythm.
 * - The first PUSH_OFF after idle is treated as "maybe movement" and kept silent.
 * - If the next PUSH_OFF comes soon enough, we allow assistance for that step.
 * - If gaps are too long, we treat it as non-walking leg movement and keep RELEASE.
 */
static bool s_model_tools_stride_guard_enabled = APP_CFG_MODEL_STRIDE_GUARD_ENABLE;
static bool s_model_tools_stride_guard_assist_allowed = false;
static bool s_model_tools_stride_guard_has_last_push_off = false;
static float s_model_tools_stride_guard_last_stride_ms = 0.0f;
static float s_model_tools_stride_guard_estimated_typical_stride_ms = 0.0f;
static float s_model_tools_stride_guard_dynamic_max_ms = 0.0f;
/* Stride timing uses frame deltas from the control loop (nominally 20 ms/frame).
 * This stays monotonic across ModelTools_HistReset(), unlike m->t_ms.
 */
static uint32_t s_model_tools_stride_guard_frame_counter = 0U;
static uint32_t s_model_tools_stride_guard_last_push_off_frame = 0U;
static float s_model_tools_stride_guard_similar_prev_stride_ms = 0.0f;
static uint8_t s_model_tools_stride_guard_similar_streak_count = 0U;
static float s_model_tools_stride_guard_compute_dynamic_max_ms(void);
static int8_t s_model_tools_polarity_hyst_with_deadband(int8_t prev_pol, float cur_value, float hyst);
static float s_model_tools_accel_centered_g(float accel_g);

static void s_model_tools_stride_guard_runtime_rearm_reset(void)
{
  /* Runtime re-arm clears only short-term cadence state:
   * - keep long-term typical stride estimate,
   * - drop active step reference and streak so next steps re-qualify stability.
   */
  s_model_tools_stride_guard_assist_allowed = false;
  s_model_tools_stride_guard_has_last_push_off = false;
  s_model_tools_stride_guard_last_push_off_frame = 0U;
  s_model_tools_stride_guard_last_stride_ms = 0.0f;
  s_model_tools_stride_guard_similar_prev_stride_ms = 0.0f;
  s_model_tools_stride_guard_similar_streak_count = 0U;
  s_model_tools_stride_guard_dynamic_max_ms = s_model_tools_stride_guard_compute_dynamic_max_ms();
}

static void s_model_tools_stride_guard_update_typical_stride(float stride_ms)
{
  const float similar_ratio = APP_CFG_MODEL_STRIDE_TYPICAL_SIMILAR_RATIO;
  const uint8_t min_streak = APP_CFG_MODEL_STRIDE_TYPICAL_MIN_STREAK;
  const float ewma_alpha = APP_CFG_MODEL_STRIDE_TYPICAL_EWMA_ALPHA;
  float diff_ms = 0.0f;
  float allowed_diff_ms = 0.0f;
  bool similar = false;

  if(stride_ms <= 0.0f)
  {
    return;
  }

  // Compare this stride with the previous stride to decide whether cadence is "similar".
  if((s_model_tools_stride_guard_similar_prev_stride_ms > 0.0f) && (similar_ratio > 0.0f))
  {
    diff_ms = fabsf(stride_ms - s_model_tools_stride_guard_similar_prev_stride_ms);
    allowed_diff_ms = fabsf(s_model_tools_stride_guard_similar_prev_stride_ms) * similar_ratio;
    similar = (diff_ms <= allowed_diff_ms);
  }

  // Similar strides extend the stable streak; dissimilar ones restart it at 1.
  if(similar)
  {
    if(s_model_tools_stride_guard_similar_streak_count < 0xFFU)
    {
      s_model_tools_stride_guard_similar_streak_count++;
    }
  }
  else
  {
    s_model_tools_stride_guard_similar_streak_count = 1U;
  }
  s_model_tools_stride_guard_similar_prev_stride_ms = stride_ms;

  // Ignore unstable periods until we observe enough consecutive similar strides.
  if(s_model_tools_stride_guard_similar_streak_count < min_streak)
  {
    return;
  }

  /* Once a stable streak is confirmed, update the long-term typical stride.
   * Flow:
   * 1) first trusted sample seeds the estimate directly,
   * 2) later trusted samples apply EWMA smoothing.
   * This keeps responsiveness while avoiding abrupt threshold jumps.
   */
  if(s_model_tools_stride_guard_estimated_typical_stride_ms <= 0.0f)
  {
    s_model_tools_stride_guard_estimated_typical_stride_ms = stride_ms;
    return;
  }

  if((ewma_alpha <= 0.0f) || (ewma_alpha >= 1.0f))
  {
    s_model_tools_stride_guard_estimated_typical_stride_ms = stride_ms;
    return;
  }

  s_model_tools_stride_guard_estimated_typical_stride_ms =
    (ewma_alpha * stride_ms) +
    ((1.0f - ewma_alpha) * s_model_tools_stride_guard_estimated_typical_stride_ms);
}

static float s_model_tools_stride_guard_compute_dynamic_max_ms(void)
{
  const float margin_ratio = APP_CFG_MODEL_STRIDE_DYNAMIC_MAX_MARGIN;
  const float min_ms = APP_CFG_MODEL_STRIDE_DYNAMIC_MAX_MIN_MS;
  const float max_ms = APP_CFG_MODEL_STRIDE_DYNAMIC_MAX_MAX_MS;
  float dynamic_ms = APP_CFG_MODEL_STRIDE_GUARD_MAX_MS;

  // Before a reliable typical stride exists, fall back to configured base max.
  if((s_model_tools_stride_guard_estimated_typical_stride_ms > 0.0f) && (margin_ratio > 0.0f))
  {
    dynamic_ms = s_model_tools_stride_guard_estimated_typical_stride_ms * margin_ratio;
  }
  // Keep runtime max inside a safe operator-tuned range.
  if(dynamic_ms < min_ms)
  {
    dynamic_ms = min_ms;
  }
  if(dynamic_ms > max_ms)
  {
    dynamic_ms = max_ms;
  }
  return dynamic_ms;
}

static float s_model_tools_sigvec3_axis_lp(const SigVec3 *v, int axis_idx, uint8_t tap_idx)
{
  if((v == NULL) || (tap_idx > 2U))
  {
    return 0.0f;
  }

  switch(axis_idx)
  {
    case 0:
      return v->x.lp[tap_idx];
    case 1:
      return v->y.lp[tap_idx];
    case 2:
      return v->z.lp[tap_idx];
    default:
      return 0.0f;
  }
}

static int8_t s_model_tools_pair_slope_sign(float older_v, float newer_v, float deadband_per_s)
{
  const float nominal_dt_ms = APP_CFG_MODEL_EXTREME_SLOPE_NOMINAL_DT_MS;
  float slope_per_s = 0.0f;

  if(nominal_dt_ms <= 0.0f)
  {
    return 0;
  }

  slope_per_s = (newer_v - older_v) * 1000.0f / nominal_dt_ms;
  if(slope_per_s > deadband_per_s)
  {
    return +1;
  }
  if(slope_per_s < -deadband_per_s)
  {
    return -1;
  }
  return 0;
}


void ModelTools_Init(Model *m)
{
  if(m == NULL)
  {
    return;
  }

  m->gyro[0] = 0.0f;
  m->gyro[1] = 0.0f;
  m->gyro[2] = 0.0f;
  m->raw_gyro_y_dps[0] = 0.0f;
  m->raw_gyro_y_dps[1] = 0.0f;
  m->raw_gyro_y_dps[2] = 0.0f;
  m->accel[0] = 0.0f;
  m->accel[1] = 0.0f;
  m->accel[2] = 0.0f;
  m->tilt_forward[0] = 0.0f;
  m->tilt_forward[1] = 0.0f;
  m->gyro_pol[0] = 0;
  m->gyro_pol[1] = 0;
  m->accel_pol[0] = 0;
  m->accel_pol[1] = 0;
  m->gyro_slope_sign[0] = 0;
  m->gyro_slope_sign[1] = 0;
  m->accel_slope_sign[0] = 0;
  m->accel_slope_sign[1] = 0;
  ModelTools_HistReset(m);

  m->gyro_dt_ms = 0.0f;
  m->thresh_time_ms = APP_CFG_MODEL_DEFAULT_THRESHOLD_TIME_MS;
  m->init_contact_valley_seen = false;
  m->stair_down_df_override_active = false;
  m->stair_down_level_between_stairs_seen = false;
  m->last_init_contact_valley_t_ms = -1e9f;
  m->last_accel_pos_peak_t_ms = -1e9f;
  m->last_accel_neg_valley_t_ms = -1e9f;
  m->last_accel_init_contact_valley_t_ms = -1e9f;
  m->state = MODEL_INIT_CONTACT;
  m->mode = MODEL_LEVEL_WALK;
  ModelTools_StrideGuardReset();
}

void ModelTools_SetMode(Model *m, ModelMode mode)
{
  if(m == NULL)
  {
    return;
  }

  if(m->mode != mode)
  {
    // Terrain-local stair-down latches should not survive an operator mode change.
    m->stair_down_df_override_active = false;
    m->stair_down_level_between_stairs_seen = false;
  }

  m->mode = mode;
}

ModelMode ModelTools_GetMode(const Model *m)
{
  return (m != NULL) ? m->mode : MODEL_LEVEL_WALK;
}

ModelState ModelTools_GetState(const Model *m)
{
  return (m != NULL) ? m->state : MODEL_FAILSAFE;
}

// Return one of the most recent gyro samples (deg/s) from the motion model.
float ModelTools_Gyro(const Model *m, int idx)
{
  return m->gyro[idx];
}

// Return one of the most recent direct vertical acc.y samples (g) from the motion model.
float ModelTools_Accel(const Model *m, int idx)
{
  return m->accel[idx];
}

bool ModelTools_GyroIncreasing(const Model *m)
{
  // Compare newest sample vs previous sample to monitor immediate trend direction.
  return (ModelTools_Gyro(m, 0) >= ModelTools_Gyro(m, 1));
}

bool ModelTools_AccelIncreasing(const Model *m)
{
  // Compare newest accel sample vs previous sample to monitor immediate trend direction.
  return (ModelTools_Accel(m, 0) >= ModelTools_Accel(m, 1));
}

bool ModelTools_GyroOverLevel(const Model *m, int idx)
{
  // Check whether turning speed magnitude is above configured "active movement" level.
  return (fabsf(ModelTools_Gyro(m, idx)) >= APP_CFG_MODEL_THRESHOLD_GYRO_DPS);
}

bool ModelTools_AccelOverLevel(const Model *m, int idx)
{
  // Check whether |acc.y - baseline| is above configured "active movement" level.
  return (fabsf(s_model_tools_accel_centered_g(ModelTools_Accel(m, idx))) >= APP_CFG_MODEL_ACCEL_TERMINAL_FLAT_PEAK_MIN_G);
}

bool ModelTools_GyroSlopeFlipUp(const Model *m)
{
  const bool prev_slope = (ModelTools_Gyro(m, 1) >= ModelTools_Gyro(m, 2));
  const bool cur_slope = ModelTools_GyroIncreasing(m);
  return (!prev_slope) && cur_slope;
}

bool ModelTools_GyroSlopeFlipDown(const Model *m)
{
  const bool prev_slope = (ModelTools_Gyro(m, 1) >= ModelTools_Gyro(m, 2));
  const bool cur_slope = ModelTools_GyroIncreasing(m);
  return prev_slope && (!cur_slope);
}

bool ModelTools_AccelSlopeFlipUp(const Model *m)
{
  const bool prev_slope = (ModelTools_Accel(m, 1) >= ModelTools_Accel(m, 2));
  const bool cur_slope = ModelTools_AccelIncreasing(m);
  return (!prev_slope) && cur_slope;
}

bool ModelTools_AccelSlopeFlipDown(const Model *m)
{
  const bool prev_slope = (ModelTools_Accel(m, 1) >= ModelTools_Accel(m, 2));
  const bool cur_slope = ModelTools_AccelIncreasing(m);
  return prev_slope && (!cur_slope);
}

bool ModelTools_IsForwardTiltInRange(const Model *m)
{
  // Forward-tilt range evaluator used by gait transitions that need tilt gating.
  return (m->tilt_forward[0] >= 0.0f) &&
         (m->tilt_forward[0] <= APP_CFG_MODEL_THRESHOLD_ANG_FORWARD_DEG);
}

float ModelTools_EventDetectTiltAbsMaxDeg(ModelMode mode)
{
  if((mode == MODEL_STAIR_UP)||(mode == MODEL_STAIR_DOWN))
  {
    return APP_CFG_MODEL_EVENT_DETECT_TILT_ABS_MAX_STAIR_DOWN_DEG;
  }
  return APP_CFG_MODEL_EVENT_DETECT_TILT_ABS_MAX_DEG;
}

bool ModelTools_IsAbsTiltWithinLimit(const Model *m, float tilt_abs_max_deg)
{
  if((m == NULL) || (tilt_abs_max_deg < 0.0f))
  {
    return false;
  }
  return fabsf(m->tilt_forward[0]) <= tilt_abs_max_deg;
}

void ModelTools_SetTiltFailsafeEnabled(bool enabled)
{
  s_model_tools_tilt_failsafe_enabled = enabled;
}

bool ModelTools_GetTiltFailsafeEnabled(void)
{
  return s_model_tools_tilt_failsafe_enabled;
}

void ModelTools_SetLevelPushOffReleaseEnabled(bool enabled)
{
  s_model_tools_level_push_off_release_enabled = enabled;
}

bool ModelTools_GetLevelPushOffReleaseEnabled(void)
{
  return s_model_tools_level_push_off_release_enabled;
}

void ModelTools_SetLevelStanceNeutralEnabled(bool enabled)
{
  s_model_tools_level_stance_neutral_enabled = enabled;
}

bool ModelTools_GetLevelStanceNeutralEnabled(void)
{
  return s_model_tools_level_stance_neutral_enabled;
}

void ModelTools_SetStrideGuardEnabled(bool enabled)
{
  s_model_tools_stride_guard_enabled = enabled;
  if(!enabled)
  {
    s_model_tools_stride_guard_assist_allowed = true;
  }
}

bool ModelTools_GetStrideGuardEnabled(void)
{
  return s_model_tools_stride_guard_enabled;
}

void ModelTools_StrideGuardReset(void)
{
  /* Reset means "start fresh":
   * no trusted cadence yet, so assistance is blocked until a valid consecutive step appears.
   */
  s_model_tools_stride_guard_runtime_rearm_reset();
  s_model_tools_stride_guard_estimated_typical_stride_ms = 0.0f;
  s_model_tools_stride_guard_dynamic_max_ms = APP_CFG_MODEL_STRIDE_GUARD_MAX_MS;
}

void ModelTools_StrideGuardOnPushOff(void)
{
  const uint32_t frame_now = s_model_tools_stride_guard_frame_counter;
  uint32_t stride_frames = 0U;
  float stride_ms = 0.0f;

  /* Stride guard decision flow:
   * 1) If stride guard is disabled, always allow assist.
   * 2) First PUSH_OFF only arms the reference point (no assist yet).
   * 3) Next PUSH_OFF events measure stride time from frame gap.
   * 4) Very long idle gaps reset trust in cadence.
   * 5) Stable repeated strides update the user's typical stride estimate.
   * 6) Build a dynamic max from that estimate, then compare current stride:
   *    - current stride <= dynamic max: allow assist
   *    - current stride > dynamic max: block assist
   */
  if(!s_model_tools_stride_guard_enabled)
  {
    // Explicit operator override: do not block assist on cadence checks.
    s_model_tools_stride_guard_assist_allowed = true;
    return;
  }

  if(!s_model_tools_stride_guard_has_last_push_off)
  {
    // First observed step only initializes timing reference; keep this one silent.
    s_model_tools_stride_guard_last_push_off_frame = frame_now;
    s_model_tools_stride_guard_has_last_push_off = true;
    s_model_tools_stride_guard_assist_allowed = false;
    s_model_tools_stride_guard_last_stride_ms = 0.0f;
    return;
  }

  stride_frames = frame_now - s_model_tools_stride_guard_last_push_off_frame;
  s_model_tools_stride_guard_last_push_off_frame = frame_now;
  stride_ms = (float)stride_frames * APP_CFG_MODEL_STRIDE_GUARD_FRAME_PERIOD_MS;
  s_model_tools_stride_guard_last_stride_ms = stride_ms;

  if(stride_ms > APP_CFG_MODEL_STRIDE_GUARD_HARD_RESET_MS)
  {
    // Long idle likely means short-term cadence is stale; keep learned typical stride and re-arm.
    s_model_tools_stride_guard_runtime_rearm_reset();
    s_model_tools_stride_guard_last_push_off_frame = frame_now;
    s_model_tools_stride_guard_has_last_push_off = true;
    return;
  }

  /* Dynamic stride guard flow:
   * - Learn/refresh typical stride only during stable cadence streaks.
   * - Compute a tolerance limit from that typical stride.
   * - Decide this step using current stride versus that tolerance.
   */
  s_model_tools_stride_guard_update_typical_stride(stride_ms);
  s_model_tools_stride_guard_dynamic_max_ms = s_model_tools_stride_guard_compute_dynamic_max_ms();
  s_model_tools_stride_guard_assist_allowed = (stride_ms <= s_model_tools_stride_guard_dynamic_max_ms);
}

bool ModelTools_StrideGuardIsAssistAllowed(void)
{
  if(!s_model_tools_stride_guard_enabled)
  {
    return true;
  }
  return s_model_tools_stride_guard_assist_allowed;
}

float ModelTools_StrideGuardGetLastStrideMs(void)
{
  return s_model_tools_stride_guard_last_stride_ms;
}

float ModelTools_StrideGuardGetEstimatedTypicalStrideMs(void)
{
  return s_model_tools_stride_guard_estimated_typical_stride_ms;
}

float ModelTools_StrideGuardGetDynamicMaxMs(void)
{
  return s_model_tools_stride_guard_dynamic_max_ms;
}

void ModelTools_TimerStep(Model *m, float dt_us)
{
  // Advance both timers from one shared dt source:
  // - gyro_dt_ms: phase dwell/hold checks
  // - t_ms: global history timeline used by peak/valley detectors
  // - stride_guard_frame_counter: monotonic push-off cadence timeline
  m->gyro_dt_ms += dt_us / 1000.0f;
  if(dt_us > 0.0f)
  {
    m->t_ms += dt_us / 1000.0f;
    s_model_tools_stride_guard_frame_counter++;
  }
}

bool ModelTools_TimerElapsed(const Model *m)
{
  // Monitor whether the measured dwell time has reached the required threshold.
  return (m->gyro_dt_ms >= m->thresh_time_ms);
}

void ModelTools_TimerReset(Model *m)
{
  // Restart duration measurement for the next gate/check cycle.
  m->gyro_dt_ms = 0.0f;
}

void ModelTools_EnterFailsafe(Model *m)
{
  if(m == NULL)
  {
    return;
  }

  m->init_contact_valley_seen = false;
  m->state = MODEL_FAILSAFE;
}

void ModelTools_TimerAlignToTime(Model *m, float ref_t_ms)
{
  if(m == NULL)
  {
    return;
  }

  // Align dwell timer to a historical event time; this backdates elapsed time.
  if((ref_t_ms >= 0.0f) && (ref_t_ms <= m->t_ms))
  {
    m->gyro_dt_ms = m->t_ms - ref_t_ms;
    return;
  }

  // Guard invalid/future timestamps so elapsed checks stay safe.
  m->gyro_dt_ms = 0.0f;
}

float ModelTools_ClampThresholdMs(float threshold_ms)
{
  const float min_ms = APP_CFG_MODEL_THRESHOLD_TIME_MIN_MS;
  const float max_ms = APP_CFG_MODEL_THRESHOLD_TIME_MAX_MS;

  if(threshold_ms < min_ms)
  {
    return min_ms;
  }
  if(threshold_ms > max_ms)
  {
    return max_ms;
  }
  return threshold_ms;
}

int8_t ModelTools_PolarityHyst(int8_t prev_pol, float cur_value)
{
  // Keep polarity stable around zero so tiny sensor noise does not flip phases.
  return s_model_tools_polarity_hyst_with_deadband(prev_pol, cur_value, APP_CFG_MODEL_GYRO_ZERO_HYST_DPS);
}

static int8_t s_model_tools_polarity_hyst_with_deadband(int8_t prev_pol, float cur_value, float hyst)
{
  // Reuse the same hysteresis state machine for both gyro and accel with independent deadbands.
  if(prev_pol > 0)
  {
    return (cur_value < -hyst) ? (int8_t)-1 : (int8_t)+1;
  }
  if(prev_pol < 0)
  {
    return (cur_value > +hyst) ? (int8_t)+1 : (int8_t)-1;
  }
  if(cur_value > +hyst)
  {
    return +1;
  }
  if(cur_value < -hyst)
  {
    return -1;
  }
  return 0;
}

bool ModelTools_IsPosGyroPol(const Model *m, int idx)
{
  return (m->gyro_pol[idx] > 0);
}

bool ModelTools_IsPosAccelPol(const Model *m, int idx)
{
  return (m->accel_pol[idx] > 0);
}

bool ModelTools_IsRawPosGyro(const Model *m, int idx, float threshold_dps)
{
  // Raw threshold check without hysteresis; caller sets near-zero acceptance policy.
  return (ModelTools_Gyro(m, idx) >= threshold_dps);
}

bool ModelTools_IsRawPosAccel(const Model *m, int idx, float threshold_g)
{
  // Raw threshold check uses centered acc.y relative to the upright-gravity baseline.
  return (s_model_tools_accel_centered_g(ModelTools_Accel(m, idx)) >= threshold_g);
}

bool ModelTools_IsRawNegAccel(const Model *m, int idx, float threshold_g)
{
  // Negative-side counterpart: caller chooses how far acc.y must sit below baseline.
  return (s_model_tools_accel_centered_g(ModelTools_Accel(m, idx)) <= -threshold_g);
}

bool ModelTools_IsNegGyroPol(const Model *m, int idx)
{
  return (m->gyro_pol[idx] < 0);
}

bool ModelTools_IsNegAccelPol(const Model *m, int idx)
{
  return (m->accel_pol[idx] < 0);
}

int8_t ModelTools_GyroSlopeSign(const Model *m, int idx)
{
  if((m == NULL) || (idx < 0) || (idx > 1))
  {
    return 0;
  }
  return m->gyro_slope_sign[idx];
}

int8_t ModelTools_AccelSlopeSign(const Model *m, int idx)
{
  if((m == NULL) || (idx < 0) || (idx > 1))
  {
    return 0;
  }
  return m->accel_slope_sign[idx];
}

void ModelTools_HistReset(Model *m)
{
  uint8_t i = 0U;

  // Reset all rolling-history state so event detection starts from a clean timeline.
  m->t_ms = 0.0f;
  m->gyro_hist_head = 0U;
  m->gyro_hist_count = 0U;
  m->last_pos_peak_t_ms = -1e9f;
  m->last_neg_valley_t_ms = -1e9f;
  m->last_init_contact_valley_t_ms = -1e9f;
  m->last_accel_pos_peak_t_ms = -1e9f;
  m->last_accel_neg_valley_t_ms = -1e9f;
  m->last_accel_init_contact_valley_t_ms = -1e9f;

  for(i = 0U; i < APP_CFG_MODEL_GYRO_HIST_LEN; i++)
  {
    m->gyro_hist_dps[i] = 0.0f;
    m->gyro_hist_pol[i] = 0;
    m->gyro_slope_hist_sign[i] = 0;
    m->accel_slope_hist_sign[i] = 0;
    m->gyro_hist_t_ms[i] = 0.0f;
    m->accel_hist_g[i] = 0.0f;
    m->accel_hist_pol[i] = 0;
    m->accel_hist_t_ms[i] = 0.0f;
  }
}

void ModelTools_HistPush(Model *m)
{
  const uint8_t next = (uint8_t)((m->gyro_hist_head + 1U) % APP_CFG_MODEL_GYRO_HIST_LEN);
  const float accel_centered_g = s_model_tools_accel_centered_g(m->accel[0]);

  // Save the newest sample (value + sign + time) in a rolling buffer for event checks.
  m->gyro_hist_head = next;
  m->gyro_hist_dps[next] = ModelTools_Gyro(m, 0);
  m->gyro_hist_pol[next] = m->gyro_pol[0];
  m->gyro_slope_hist_sign[next] = m->gyro_slope_sign[0];
  m->accel_slope_hist_sign[next] = m->accel_slope_sign[0];
  m->gyro_hist_t_ms[next] = m->t_ms;
  // Keep accel history centered at baseline so peak/valley logic runs in centered space.
  m->accel_hist_g[next] = accel_centered_g;
  m->accel_hist_pol[next] = m->accel_pol[0];
  m->accel_hist_t_ms[next] = m->t_ms;
  if(m->gyro_hist_count < APP_CFG_MODEL_GYRO_HIST_LEN)
  {
    m->gyro_hist_count++;
  }
}

typedef struct
{
  const float *hist_v;
  const int8_t *hist_pol;
  const float *hist_t_ms;
  uint8_t hist_head;
  uint8_t hist_count;
  float t_now_ms;
  float cur_v;
  float slope_deadband_per_s;
  float peak_window_ms;
  float peak_confirm_ms;
  float terminal_flat_peak_min;
  float terminal_flat_peak_retrace;
} ModeltoolsExtremeSignalCtx;

static uint8_t s_model_tools_hist_idx_from_newest_ctx(const ModeltoolsExtremeSignalCtx *ctx, uint8_t newest_offset)
{
  return (uint8_t)((ctx->hist_head + APP_CFG_MODEL_GYRO_HIST_LEN - newest_offset) % APP_CFG_MODEL_GYRO_HIST_LEN);
}

static int8_t s_model_tools_hist_slope_sign_ctx(const ModeltoolsExtremeSignalCtx *ctx,
                                               float older_v,
                                               float older_t_ms,
                                               float newer_v,
                                               float newer_t_ms)
{
  float dt_ms = newer_t_ms - older_t_ms;
  const float nominal_dt_ms = APP_CFG_MODEL_EXTREME_SLOPE_NOMINAL_DT_MS;
  const float valid_min_dt_ms = APP_CFG_MODEL_EXTREME_SLOPE_VALID_DT_MIN_MS;
  const float valid_max_dt_ms = APP_CFG_MODEL_EXTREME_SLOPE_VALID_DT_MAX_MS;

  /* Pairwise slope dt guard:
   * - nominal sampling is 20ms, but loop jitter can produce outlier dt gaps,
   * - for non-positive/out-of-band dt, fall back to nominal dt so slope sign
   *   remains meaningful instead of being forced to zero.
   */
  if((dt_ms <= 0.0f) || (dt_ms < valid_min_dt_ms) || (dt_ms > valid_max_dt_ms))
  {
    dt_ms = nominal_dt_ms;
  }
  return s_model_tools_pair_slope_sign(older_v,
                                      newer_v,
                                      ctx->slope_deadband_per_s * (nominal_dt_ms / dt_ms));
}

static uint8_t s_model_tools_hist_pick_extreme_offset(const ModeltoolsExtremeSignalCtx *ctx,
                                                     uint8_t newest_offset_start,
                                                     uint8_t newest_offset_end,
                                                     bool want_max)
{
  uint8_t newest_offset = 0U;
  uint8_t best_offset = newest_offset_start;
  float best_v = ctx->hist_v[s_model_tools_hist_idx_from_newest_ctx(ctx, newest_offset_start)];

  for(newest_offset = (uint8_t)(newest_offset_start + 1U); newest_offset <= newest_offset_end; newest_offset++)
  {
    const uint8_t idx = s_model_tools_hist_idx_from_newest_ctx(ctx, newest_offset);
    const float v = ctx->hist_v[idx];
    if(want_max)
    {
      if(v >= best_v)
      {
        best_v = v;
        best_offset = newest_offset;
      }
    }
    else
    {
      if(v <= best_v)
      {
        best_v = v;
        best_offset = newest_offset;
      }
    }
  }
  return best_offset;
}

typedef enum
{
  MODELTOOLS_EXTREME_KIND_FLIP = 0,
  MODELTOOLS_EXTREME_KIND_FLAT_CONTINUE = 1,
  MODELTOOLS_EXTREME_KIND_TERMINAL_FLAT_PEAK = 2
} ModeltoolsExtremeKind;

static bool s_model_tools_hist_find_extreme_internal(const ModeltoolsExtremeSignalCtx *ctx,
                                                    float window_ms,
                                                    int8_t pol_required,
                                                    bool want_max,
                                                    float *ext_val_out,
                                                    float *ext_t_ms_out,
                                                    ModeltoolsExtremeKind *kind_out)
{
  uint8_t newest_offset = 0U;
  const float t_now = (ctx != NULL) ? ctx->t_now_ms : 0.0f;
  int last_nz_sign = 0;
  int last_nz_edge = -1;
  bool saw_zero_run = false;
  int zero_run_start_edge = -1;
  int zero_run_end_edge = -1;

  if((ctx == NULL) || (ctx->hist_count == 0U))
  {
    return false;
  }

  /* Plain-language flow:
   * - We walk from newest samples toward older samples.
   * - For each neighbor pair, we ask "is the curve going up (+), down (-), or flat (0)?"
   * - A candidate extreme is created when:
   *   1) direction flips (up to down or down to up), or
   *   2) direction pauses flat and then continues the same way (+ -> 0 -> + or - -> 0 -> -).
   * - Once a candidate passes type/polarity filters, we return immediately because
   *   this scan order guarantees it is the newest valid extreme in the window.
   */
  for(newest_offset = 0U; (newest_offset + 1U) < ctx->hist_count; newest_offset++)
  {
    const uint8_t idx_newer = s_model_tools_hist_idx_from_newest_ctx(ctx, newest_offset);
    const uint8_t idx_older = s_model_tools_hist_idx_from_newest_ctx(ctx, (uint8_t)(newest_offset + 1U));
    const float t_newer = ctx->hist_t_ms[idx_newer];
    const float t_older = ctx->hist_t_ms[idx_older];
    int sign = 0;

    if(((t_now - t_newer) > window_ms) || ((t_now - t_older) > window_ms))
    {
      break;
    }

    sign = (int)s_model_tools_hist_slope_sign_ctx(ctx,
                                                 ctx->hist_v[idx_older],
                                                 t_older,
                                                 ctx->hist_v[idx_newer],
                                                 t_newer);
    if(sign == 0)
    {
      if(last_nz_sign != 0)
      {
        // We are inside a flat bridge after a known direction; remember its range.
        if(!saw_zero_run)
        {
          saw_zero_run = true;
          zero_run_start_edge = (int)newest_offset;
        }
        zero_run_end_edge = (int)newest_offset;
      }
      continue;
    }

    if(last_nz_sign != 0)
    {
      // Two ways to form an extreme candidate:
      // - flip turn: direction changed
      // - flat continuation: direction paused at zero, then resumed same sign
      const bool is_flip_turn = (sign != last_nz_sign);
      const bool is_flat_continue = saw_zero_run && (sign == last_nz_sign) &&
                                    (zero_run_start_edge >= 0) && (zero_run_end_edge >= zero_run_start_edge);
      const bool should_emit_candidate = is_flip_turn || is_flat_continue;

      if(should_emit_candidate && (last_nz_edge >= 0))
      {
        // For flip turns, choose only the requested type (peak or valley).
        // For flat continuation, accept both modes and let max/min chooser decide.
        const bool is_peak_turn = (last_nz_sign < 0) && (sign > 0);
        const bool is_valley_turn = (last_nz_sign > 0) && (sign < 0);
        const bool type_match = is_flat_continue ? true : (want_max ? is_peak_turn : is_valley_turn);
        const uint8_t chosen_offset = s_model_tools_hist_pick_extreme_offset(ctx,
                                                                            (uint8_t)last_nz_edge,
                                                                            newest_offset,
                                                                            want_max);
        const uint8_t idx_chosen = s_model_tools_hist_idx_from_newest_ctx(ctx, chosen_offset);
        const int8_t pol = ctx->hist_pol[idx_chosen];

        if(type_match && !(((pol_required > 0) && (pol <= 0)) || ((pol_required < 0) && (pol >= 0))))
        {
          if(ext_val_out != NULL)
          {
            *ext_val_out = ctx->hist_v[idx_chosen];
          }
          if(ext_t_ms_out != NULL)
          {
            *ext_t_ms_out = ctx->hist_t_ms[idx_chosen];
          }
          if(kind_out != NULL)
          {
            *kind_out = is_flat_continue ? MODELTOOLS_EXTREME_KIND_FLAT_CONTINUE
                                         : MODELTOOLS_EXTREME_KIND_FLIP;
          }
          return true;
        }
      }
    }

    last_nz_sign = sign;
    last_nz_edge = (int)newest_offset;
    saw_zero_run = false;
    zero_run_start_edge = -1;
    zero_run_end_edge = -1;
  }

  /* Terminal flat-plateau handling (peak-only):
   * If scan ends while still inside a zero-slope run after a known direction,
   * emit a dedicated terminal-flat PEAK candidate from that final segment.
   * This solves the "steady crest to window tail" miss without enabling broad
   * flat-continue behavior that can be overly sensitive to opposite-direction
   * motion.
   */
  if(want_max &&
     saw_zero_run && (last_nz_sign != 0) && (last_nz_edge >= 0) &&
     (zero_run_start_edge >= 0) && (zero_run_end_edge >= zero_run_start_edge))
  {
    const uint8_t chosen_offset = s_model_tools_hist_pick_extreme_offset(ctx,
                                                                        (uint8_t)last_nz_edge,
                                                                        (uint8_t)zero_run_end_edge,
                                                                        want_max);
    const uint8_t idx_chosen = s_model_tools_hist_idx_from_newest_ctx(ctx, chosen_offset);
    const int8_t pol = ctx->hist_pol[idx_chosen];

    if(!(((pol_required > 0) && (pol <= 0)) || ((pol_required < 0) && (pol >= 0))))
    {
      if(ext_val_out != NULL)
      {
        *ext_val_out = ctx->hist_v[idx_chosen];
      }
      if(ext_t_ms_out != NULL)
      {
        *ext_t_ms_out = ctx->hist_t_ms[idx_chosen];
      }
      if(kind_out != NULL)
      {
        *kind_out = MODELTOOLS_EXTREME_KIND_TERMINAL_FLAT_PEAK;
      }
      return true;
    }
  }
  return false;
}

static bool s_model_tools_detect_confirmed_extreme(const ModeltoolsExtremeSignalCtx *ctx,
                                                  int8_t pol_required,
                                                  bool want_max,
                                                  float retrace_value,
                                                  bool include_flat_continue,
                                                  float *last_extreme_t_ms)
{
  float extreme = 0.0f;
  float t_extreme = 0.0f;
  ModeltoolsExtremeKind extreme_kind = MODELTOOLS_EXTREME_KIND_FLIP;
  float retrace_level = 0.0f;
  bool retrace_ok = false;

  if((ctx == NULL) || (last_extreme_t_ms == NULL))
  {
    return false;
  }

  /* Shared confirmed-extreme flow:
   * 1) Get newest extreme candidate (from either flip-turn or flat-continuation path).
   * 2) Ignore it if that same timestamp was already reported.
   * 3) Wait a short confirm delay so we do not trigger on an unstable point.
   * 4) Apply caller policy gate for flat-continuation candidates.
   * 5) Confirm retrace:
   *    - flip candidate: direction-aware retrace (peak down / valley up),
   *    - flat candidate: either-direction retrace away from the flat extreme.
   */
  if(!s_model_tools_hist_find_extreme_internal(ctx,
                                              ctx->peak_window_ms,
                                              pol_required,
                                              want_max,
                                              &extreme,
                                              &t_extreme,
                                              &extreme_kind))
  {
    return false;
  }
  if(t_extreme <= *last_extreme_t_ms)
  {
    return false;
  }
  if((ctx->t_now_ms - t_extreme) < ctx->peak_confirm_ms)
  {
    return false;
  }
  if((extreme_kind == MODELTOOLS_EXTREME_KIND_FLAT_CONTINUE) && (!include_flat_continue))
  {
    return false;
  }

  if(extreme_kind == MODELTOOLS_EXTREME_KIND_FLAT_CONTINUE)
  {
    // Flat continuation can resume either direction, so any sufficient move away confirms.
    retrace_ok = (fabsf(ctx->cur_v - extreme) >= retrace_value);
  }
  else if(extreme_kind == MODELTOOLS_EXTREME_KIND_TERMINAL_FLAT_PEAK)
  {
    /* Peak-only terminal flat confirmation:
     * 1) require a minimum peak magnitude so quiet standing/lean noise does
     *    not start a cycle,
     * 2) use a stronger directional retrace so opposite-direction motion alone
     *    cannot satisfy confirmation.
     */
    if(extreme < ctx->terminal_flat_peak_min)
    {
      retrace_ok = false;
    }
    else
    {
      retrace_level = extreme - ctx->terminal_flat_peak_retrace;
      retrace_ok = (ctx->cur_v <= retrace_level);
    }
  }
  else
  {
    retrace_level = want_max ? (extreme - retrace_value)
                             : (extreme + retrace_value);
    retrace_ok = want_max ? (ctx->cur_v <= retrace_level)
                          : (ctx->cur_v >= retrace_level);
  }
  if(!retrace_ok)
  {
    return false;
  }

  *last_extreme_t_ms = t_extreme;
  return true;
}

static ModeltoolsExtremeSignalCtx s_model_tools_build_gyro_ctx(const Model *m)
{
  ModeltoolsExtremeSignalCtx ctx = {0};
  if(m == NULL)
  {
    return ctx;
  }

  ctx.hist_v = m->gyro_hist_dps;
  ctx.hist_pol = m->gyro_hist_pol;
  ctx.hist_t_ms = m->gyro_hist_t_ms;
  ctx.hist_head = m->gyro_hist_head;
  ctx.hist_count = m->gyro_hist_count;
  ctx.t_now_ms = m->t_ms;
  ctx.cur_v = ModelTools_Gyro(m, 0);
  ctx.slope_deadband_per_s = APP_CFG_MODEL_GYRO_EXTREME_SLOPE_DEADBAND_DPS2;
  ctx.peak_window_ms = APP_CFG_MODEL_GYRO_PEAK_WINDOW_MS;
  ctx.peak_confirm_ms = APP_CFG_MODEL_GYRO_PEAK_CONFIRM_MS;
  ctx.terminal_flat_peak_min = APP_CFG_MODEL_GYRO_TERMINAL_FLAT_PEAK_MIN_DPS;
  ctx.terminal_flat_peak_retrace = APP_CFG_MODEL_GYRO_TERMINAL_FLAT_PEAK_RETRACE_DPS;
  return ctx;
}

static ModeltoolsExtremeSignalCtx s_model_tools_build_accel_ctx(const Model *m)
{
  ModeltoolsExtremeSignalCtx ctx = {0};
  if(m == NULL)
  {
    return ctx;
  }

  ctx.hist_v = m->accel_hist_g;
  ctx.hist_pol = m->accel_hist_pol;
  ctx.hist_t_ms = m->accel_hist_t_ms;
  ctx.hist_head = m->gyro_hist_head;
  ctx.hist_count = m->gyro_hist_count;
  ctx.t_now_ms = m->t_ms;
  // Keep current accel sample in the same centered space as accel_hist_g.
  ctx.cur_v = s_model_tools_accel_centered_g(m->accel[0]);
  ctx.slope_deadband_per_s = APP_CFG_MODEL_ACCEL_EXTREME_SLOPE_DEADBAND_G_S;
  ctx.peak_window_ms = APP_CFG_MODEL_ACCEL_PEAK_WINDOW_MS;
  ctx.peak_confirm_ms = APP_CFG_MODEL_ACCEL_PEAK_CONFIRM_MS;
  ctx.terminal_flat_peak_min = APP_CFG_MODEL_ACCEL_TERMINAL_FLAT_PEAK_MIN_G;
  ctx.terminal_flat_peak_retrace = APP_CFG_MODEL_ACCEL_TERMINAL_FLAT_PEAK_RETRACE_G;
  return ctx;
}

bool ModelTools_DetectGyroPosPeak(Model *m)
{
  if(m == NULL)
  {
    return false;
  }
  const ModeltoolsExtremeSignalCtx ctx = s_model_tools_build_gyro_ctx(m);
  // Positive-only peak detector for the push-off crest confirmation.
  return s_model_tools_detect_confirmed_extreme(&ctx,
                                               0,
                                               true,
                                               APP_CFG_MODEL_GYRO_PEAK_RETRACE_STRONG_DPS,
                                               false,
                                               &m->last_pos_peak_t_ms);
}

bool ModelTools_DetectGyroNegValley(Model *m)
{
  if(m == NULL)
  {
    return false;
  }
  const ModeltoolsExtremeSignalCtx ctx = s_model_tools_build_gyro_ctx(m);
  // Negative-only valley detector for phases that explicitly require negative rotation.
  return s_model_tools_detect_confirmed_extreme(&ctx,
                                               -1,
                                               false,
                                               APP_CFG_MODEL_GYRO_PEAK_RETRACE_WEAK_DPS,
                                               false,
                                               &m->last_neg_valley_t_ms);
}

bool ModelTools_DetectGyroInitContactValley(Model *m)
{
  if(m == NULL)
  {
    return false;
  }
  const ModeltoolsExtremeSignalCtx ctx = s_model_tools_build_gyro_ctx(m);
  /* INIT_CONTACT valley flow:
   * 1) detect a confirmed history valley with no sign constraint,
   * 2) require retrace so acceptance is a true fall-then-rise pattern.
   * Early strong negative over-level rejection remains caller-owned.
   */
  return s_model_tools_detect_confirmed_extreme(&ctx,
                                               -1,
                                               false,
                                               APP_CFG_MODEL_GYRO_PEAK_RETRACE_WEAK_DPS,
                                               true,
                                               &m->last_init_contact_valley_t_ms);
}

bool ModelTools_DetectAccelPosPeak(Model *m)
{
  if(m == NULL)
  {
    return false;
  }
  const ModeltoolsExtremeSignalCtx ctx = s_model_tools_build_accel_ctx(m);
  return s_model_tools_detect_confirmed_extreme(&ctx,
                                               0,
                                               true,
                                               APP_CFG_MODEL_ACCEL_PEAK_RETRACE_STRONG_G,
                                               false,
                                               &m->last_accel_pos_peak_t_ms);
}

bool ModelTools_DetectAccelNegValley(Model *m)
{
  if(m == NULL)
  {
    return false;
  }
  const ModeltoolsExtremeSignalCtx ctx = s_model_tools_build_accel_ctx(m);
  return s_model_tools_detect_confirmed_extreme(&ctx,
                                               -1,
                                               false,
                                               APP_CFG_MODEL_ACCEL_PEAK_RETRACE_WEAK_G,
                                               false,
                                               &m->last_accel_neg_valley_t_ms);
}

ModelPushOffPeakState ModelTools_DetectPushOffPeakPair(Model *m)
{
  const bool gyro_peak_new = ModelTools_DetectGyroPosPeak(m);
  const bool accel_peak_new = ModelTools_DetectAccelPosPeak(m);
  const bool have_gyro_peak = (m != NULL) && (m->last_pos_peak_t_ms > -1e8f);
  const bool have_accel_peak = (m != NULL) && (m->last_accel_pos_peak_t_ms > -1e8f);
  const float pair_window_ms = APP_CFG_MODEL_PUSH_OFF_PAIR_WINDOW_MS;
  float dt_ms = 0.0f;

  if(m == NULL)
  {
    return MODEL_PUSH_OFF_PEAK_NONE;
  }

  /* Push-off peak pairing flow:
   * 1) run both one-shot detectors every cycle so each can refresh its own timestamp,
   * 2) if either side is new and both timestamps exist, try paired classification first,
   * 3) if both exist but are too far apart, keep the *new* side as single-sensor evidence,
   * 4) only when opposite side has no historical peak, emit classic single-sensor states.
   * This avoids the "both exist but misaligned => NONE" dead zone.
   */
  if((gyro_peak_new && have_accel_peak) || (accel_peak_new && have_gyro_peak) || (gyro_peak_new && accel_peak_new))
  {
    dt_ms = fabsf(m->last_pos_peak_t_ms - m->last_accel_pos_peak_t_ms);
    if(dt_ms <= pair_window_ms)
    {
      return MODEL_PUSH_OFF_PEAK_PAIRED;
    }
    if(gyro_peak_new && !accel_peak_new)
    {
      return MODEL_PUSH_OFF_PEAK_GYRO_ONLY;
    }
    if(accel_peak_new && !gyro_peak_new)
    {
      return MODEL_PUSH_OFF_PEAK_ACCEL_ONLY;
    }
    if(gyro_peak_new && accel_peak_new)
    {
      // Deterministic tie-break for same-cycle misaligned detections: prioritize gyro.
      return MODEL_PUSH_OFF_PEAK_GYRO_ONLY;
    }
  }
  if(gyro_peak_new && !have_accel_peak)
  {
    return MODEL_PUSH_OFF_PEAK_GYRO_ONLY;
  }
  if(accel_peak_new && !have_gyro_peak)
  {
    return MODEL_PUSH_OFF_PEAK_ACCEL_ONLY;
  }
  return MODEL_PUSH_OFF_PEAK_NONE;
}

float ModelTools_ForwardTiltAccOnlyDeg(const Signal *sig)
{
  const float side_sign = IS_LEFT_RT() ? -1.0f : 1.0f;
  float ay = 0.0f;
  float az = 0.0f;
  float tilt_acc_deg = 0.0f;

  if(sig == NULL)
  {
    return 0.0f;
  }

  ay = s_model_tools_sigvec3_axis_lp(&sig->acc, SIGNAL_TILT_Y_AXIS, 0U) * (float)SIGNAL_TILT_Y_SIGN;
  az = s_model_tools_sigvec3_axis_lp(&sig->acc, SIGNAL_TILT_Z_AXIS, 0U) * (float)SIGNAL_TILT_Z_SIGN;
  tilt_acc_deg = atan2f(ay, az) * (180.0f / 3.14159265358979323846f);
  return side_sign * tilt_acc_deg;
}

static float s_model_tools_forward_acc_y_g(const Signal *sig, uint8_t tap_idx)
{
  if((sig == NULL) || (tap_idx > 2U))
  {
    return 0.0f;
  }
  // acc.y is global vertical and does not depend on side; use direct LP tap.
  return sig->acc.y.lp[tap_idx];
}

static float s_model_tools_accel_centered_g(float accel_g)
{
  return accel_g - APP_CFG_MODEL_ACCEL_BASELINE_G;
}

void ModelTools_UpdateSignal(Model *m, const Signal *sig)
{
  const float side_sign = IS_LEFT_RT() ? 1.0f : -1.0f;

  if((m == NULL) || (sig == NULL))
  {
    return;
  }

  // Normalize sensor direction so left/right legs share one common sign convention.
  m->gyro[0] = side_sign * sig->gyro.z.lp[0];
  m->gyro[1] = side_sign * sig->gyro.z.lp[1];
  m->gyro[2] = side_sign * sig->gyro.z.lp[2];
  m->raw_gyro_y_dps[0] = sig->gyro.y.lp[0];
  m->raw_gyro_y_dps[1] = sig->gyro.y.lp[1];
  m->raw_gyro_y_dps[2] = sig->gyro.y.lp[2];
  // Keep two live monitors for downstream phase logic:
  // - polarity: stable direction label (+ / - / 0) with anti-noise hysteresis
  m->gyro_pol[1] = m->gyro_pol[0];
  m->gyro_pol[0] = ModelTools_PolarityHyst(m->gyro_pol[1], m->gyro[0]);
  m->gyro_slope_sign[1] = m->gyro_slope_sign[0];
  m->gyro_slope_sign[0] = s_model_tools_pair_slope_sign(m->gyro[1],
                                                        m->gyro[0],
                                                        APP_CFG_MODEL_GYRO_EXTREME_SLOPE_DEADBAND_DPS2);

  // Accelerometer counterpart path now uses direct vertical acc.y in g:
  // 1) read LP tap history directly from acc.y (no side remap),
  // 2) apply polarity hysteresis in centered space (acc.y - baseline),
  // 3) compute slope sign on raw acc.y samples (offset-invariant).
  m->accel[0] = s_model_tools_forward_acc_y_g(sig, 0U);
  m->accel[1] = s_model_tools_forward_acc_y_g(sig, 1U);
  m->accel[2] = s_model_tools_forward_acc_y_g(sig, 2U);
  m->accel_pol[1] = m->accel_pol[0];
  m->accel_pol[0] = s_model_tools_polarity_hyst_with_deadband(m->accel_pol[1],
                                                              s_model_tools_accel_centered_g(m->accel[0]),
                                                              APP_CFG_MODEL_ACCEL_ZERO_HYST_G);
  m->accel_slope_sign[1] = m->accel_slope_sign[0];
  m->accel_slope_sign[0] = s_model_tools_pair_slope_sign(m->accel[1],
                                                         m->accel[0],
                                                         APP_CFG_MODEL_ACCEL_SLOPE_DEADBAND_G_S);

  m->tilt_forward[1] = m->tilt_forward[0];
  m->tilt_forward[0] = sig->tilt_forward.lp[0];
}

ModelOutput ModelTools_ActionFromTable(const Model *m,
                                       const ModelOutput action_table[MODEL_MODE_COUNT][MODEL_STATE_COUNT])
{
  const int mode = (m != NULL) ? (int)m->mode : -1;
  const int state = (m != NULL) ? (int)m->state : -1;

  if((mode < 0) || (mode >= MODEL_MODE_COUNT) || (state < 0) || (state >= MODEL_STATE_COUNT))
  {
    return MODEL_OUTPUT_RELEASE;
  }
  return action_table[mode][state];
}
