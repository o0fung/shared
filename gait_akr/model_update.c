#include "modes/gait/model_update.h"
#include "modes/gait/model_tools.h"

#include <math.h>
#include <stddef.h>

ModelState ModelUpdate_EventDetection(Model *m, float delta_t_us)
{
  ModelState prev_state = MODEL_FAILSAFE;
  ModelState next_state = MODEL_FAILSAFE;

  if(m == NULL)
  {
    return MODEL_FAILSAFE;
  }

  prev_state = m->state;
  ModelTools_TimerStep(m, delta_t_us);
  // Each loop records the newest gyro sample first, so all checks use current motion.
  ModelTools_HistPush(m);

  /* Optional terrain-aware absolute-tilt failsafe gate:
   * 1) when enabled, choose a limit from terrain mode,
   * 2) if posture tilt magnitude is too large, block event detection and clear stale phase context,
   * 3) force FAILSAFE and exit this cycle; FSM resumes once tilt returns within the selected limit.
   */
  if(ModelTools_GetTiltFailsafeEnabled())
  {
    const float tilt_abs_max_deg = ModelTools_EventDetectTiltAbsMaxDeg(m->mode);
    if(!ModelTools_IsAbsTiltWithinLimit(m, tilt_abs_max_deg))
    {
      ModelTools_TimerReset(m);
      ModelTools_EnterFailsafe(m);
      return m->state;
    }
  }

  const bool is_stair_up = (m->mode == MODEL_STAIR_UP);
  const bool is_stair_down = (m->mode == MODEL_STAIR_DOWN);
  const float push_off_timeout_ms =
    is_stair_up ? APP_CFG_MODEL_STAIR_UP_PUSH_OFF_TIMEOUT_MS : APP_CFG_MODEL_PUSH_OFF_TIMEOUT_MS;
  const float init_swing_timeout_ms =
    is_stair_up ? APP_CFG_MODEL_STAIR_UP_INIT_SWING_TIMEOUT_MS : APP_CFG_MODEL_INIT_SWING_TIMEOUT_MS;
  const float mid_swing_pos_gyro_min_dps =
    is_stair_up ? APP_CFG_MODEL_STAIR_UP_MID_SWING_POS_GYRO_MIN_DPS :
                  APP_CFG_MODEL_MID_SWING_POS_GYRO_MIN_DPS;

  /* Unified gait event flow:
   * 1) INIT_CONTACT waits until the foot has stayed quiet long enough to trust contact.
   * 2) STANCE watches for the terrain-specific sign of push-off:
   *    - level walk and stair-down use a positive gyro peak,
   *    - stair-up uses a centered vertical-accel drop that marks loading/upward drive.
   * 3) PUSH_OFF ends when motion shows the leg has left push-off:
   *    - level walk and stair-down wait for negative gyro polarity,
   *    - stair-up waits for vertical acceleration to turn back downward.
   * 4) INIT_SWING and MID_SWING are shared: find the negative swing valley, then wait
   *    for near-zero/positive gyro before re-arming contact detection for the next step.
   * 5) Stair-down keeps one extra per-step latch so its action table can release PF during
   *    swing when turning/between-stairs evidence says normal stair-down assist is risky.
   */
  switch(m->state)
  {
    case MODEL_FAILSAFE:
    case MODEL_INIT_CONTACT:
      {
        const bool timer_elapsed = ModelTools_TimerElapsed(m);
        const bool valley_detected = ModelTools_IsNegGyroPol(m, 0) && ModelTools_DetectGyroNegValley(m);
        const bool terminal_swing = ModelTools_IsRawPosGyro(m, 0, APP_CFG_MODEL_MID_SWING_POS_GYRO_MIN_DPS);

        /* INIT_CONTACT transition priority:
         * 1) the dwell timer is the normal path into stance,
         * 2) if a swing-shaped gyro valley was seen, keep waiting until terminal-swing gyro clears it,
         * 3) while waiting, latch any new negative valley so stance does not start mid-swing.
         */
        if(timer_elapsed)
        {
          ModelTools_TimerReset(m);
          ModelTools_HistReset(m);
          
          if(m->init_contact_valley_seen)
          {
            // A valley appeared during contact dwell, so restart and wait for swing to finish cleanly.
            m->state = MODEL_INIT_CONTACT;
            break;
          }

          // Contact dwell completed without pending swing evidence; begin stance/push-off detection.
          m->state = MODEL_STANCE_BASE;
          break;
        }

        if(m->init_contact_valley_seen && terminal_swing)
        {
          // The leg has come forward after a latched valley; clear old swing evidence and restart dwell.
          ModelTools_TimerReset(m);
          ModelTools_HistReset(m);
          m->thresh_time_ms = APP_CFG_MODEL_DEFAULT_THRESHOLD_TIME_MS;
          m->init_contact_valley_seen = false;
          m->state = MODEL_INIT_CONTACT;
          break;
        }

        if(valley_detected)
        {
          // Latch swing-shaped evidence; the timer path above will keep contact from starting too early.
          m->init_contact_valley_seen = true;
          break;
        }
      }
      break;

    case MODEL_STANCE_BASE:
    case MODEL_STANCE_GYRO:
    case MODEL_STANCE_ACCEL:
      {
        const bool push_off_detected =
          is_stair_up ? ModelTools_IsRawNegAccel(m, 0, APP_CFG_MODEL_STAIR_UP_PUSH_OFF_NEG_ACCEL_MIN_G) :
                        ModelTools_DetectGyroPosPeak(m);

        /* Stance has legacy substates, but this detector treats them as one support phase.
         * Normalizing immediately avoids adding an extra loop before the push-off trigger is tested.
         */
        m->state = MODEL_STANCE_BASE;

        if(push_off_detected)
        {
          // Terrain mode picks the trigger: stair-up accel drive, otherwise gyro toe-off crest.
          ModelTools_TimerReset(m);
          m->state = MODEL_PUSH_OFF;
        }
      }
      break;

    case MODEL_PUSH_OFF:
      {
        const bool push_off_finished =
          is_stair_up ? ModelTools_AccelSlopeFlipDown(m) : ModelTools_IsNegGyroPol(m, 0);

        /* PUSH_OFF exit flow:
         * 1) prefer the terrain-specific motion shape that says the assist phase is complete,
         * 2) if that shape never arrives, timeout through FAILSAFE so assist cannot hold forever.
         */
        if(push_off_finished)
        {
          // Push-off has ended; start looking for the swing valley.
          ModelTools_TimerReset(m);
          m->state = MODEL_INIT_SWING;
        }
        else if(m->gyro_dt_ms >= push_off_timeout_ms)
        {
          // Push-off lasted too long for this terrain mode; force RELEASE through FAILSAFE.
          ModelTools_TimerReset(m);
          ModelTools_EnterFailsafe(m);
        }
      }
      break;

    case MODEL_INIT_SWING:
      {
        const bool swing_valley_detected = ModelTools_IsNegGyroPol(m, 0) && ModelTools_GyroSlopeFlipUp(m);

        /* INIT_SWING flow:
         * 1) the negative gyro valley means the leg is in the middle of swing,
         * 2) timeout releases assistance if the valley never appears.
         */
        if(swing_valley_detected)
        {
          m->state = MODEL_MID_SWING;
        }
        else if(m->gyro_dt_ms >= init_swing_timeout_ms)
        {
          ModelTools_TimerReset(m);
          ModelTools_EnterFailsafe(m);
        }
      }
      break;

    case MODEL_MID_SWING:
      {
        const bool terminal_swing =
          ModelTools_IsRawPosGyro(m, 0, mid_swing_pos_gyro_min_dps);

        /* MID_SWING completion:
         * near-zero/positive gyro means the leg has come forward enough to prepare for contact again.
         * Stair-up uses a looser threshold because its swing shape is different from level walking.
         */
        if(terminal_swing)
        {
          m->thresh_time_ms = ModelTools_ClampThresholdMs(m->gyro_dt_ms);
          ModelTools_TimerReset(m);
          ModelTools_HistReset(m);
          m->init_contact_valley_seen = false;
          m->state = MODEL_INIT_CONTACT;
        }
      }
      break;

    default:
      // Unknown state: rebuild contact detection from a conservative default dwell window.
      m->thresh_time_ms = APP_CFG_MODEL_DEFAULT_THRESHOLD_TIME_MS;
      m->init_contact_valley_seen = false;
      m->state = MODEL_INIT_CONTACT;
      break;
  }

  next_state = m->state;

  /* Stair-down swing override flow:
   * 1) exactly when the step enters INIT_SWING, freeze the override decision for that step,
   * 2) keep it only through INIT_SWING/MID_SWING where stair-down would normally provide PF,
   * 3) clear it as soon as the FSM returns to contact/stance/push-off.
   */
  if(is_stair_down &&
     (prev_state != MODEL_INIT_SWING) &&
     (next_state == MODEL_INIT_SWING))
  {
    const bool level_between_stairs = false;
    const bool turning_between_stairs =
      (fabsf(m->raw_gyro_y_dps[0]) > APP_CFG_MODEL_STAIR_DOWN_PUSH_OFF_TURN_GYRO_Y_MIN_DPS);

    // Current firmware keeps the level-between-stairs accel latch disabled; turning still suppresses PF.
    m->stair_down_df_override_active = level_between_stairs || turning_between_stairs;
    m->stair_down_level_between_stairs_seen = false;
  }
  else if(is_stair_down &&
          (next_state != MODEL_INIT_SWING) &&
          (next_state != MODEL_MID_SWING))
  {
    // Outside stair-down swing assist states, no override should remain active.
    m->stair_down_df_override_active = false;
    if(next_state != MODEL_PUSH_OFF)
    {
      // PUSH_OFF is still part of the current step, so keep any stance evidence until swing consumes it.
      m->stair_down_level_between_stairs_seen = false;
    }
  }

  if((prev_state != MODEL_PUSH_OFF) && (next_state == MODEL_PUSH_OFF))
  {
    // Each new PUSH_OFF marks one step edge for stride-timing trust evaluation.
    ModelTools_StrideGuardOnPushOff();
  }

  return next_state;
}

ModelOutput ModelUpdate_Action(const Model *m)
{
  ModelOutput output = MODEL_OUTPUT_RELEASE;
  // Event detection chooses state; this table maps (mode,state) to actuator intent.
  static const ModelOutput action_table[MODEL_MODE_COUNT][MODEL_STATE_COUNT] = {
    [MODEL_STAIR_DOWN] = {
      [MODEL_FAILSAFE] = MODEL_OUTPUT_RELEASE,
      [MODEL_INIT_CONTACT] = MODEL_OUTPUT_RELEASE,
      [MODEL_STANCE_BASE] = MODEL_OUTPUT_RELEASE,
      [MODEL_STANCE_GYRO] = MODEL_OUTPUT_RELEASE,
      [MODEL_STANCE_ACCEL] = MODEL_OUTPUT_RELEASE,
      [MODEL_PUSH_OFF] = MODEL_OUTPUT_RELEASE,
      [MODEL_INIT_SWING] = MODEL_OUTPUT_PF,
      [MODEL_MID_SWING] = MODEL_OUTPUT_PF_FADE,
    },
    [MODEL_LEVEL_WALK] = {
      [MODEL_FAILSAFE] = MODEL_OUTPUT_RELEASE,          // Free to move for Initial Contact
      [MODEL_INIT_CONTACT] = MODEL_OUTPUT_RELEASE,
      [MODEL_STANCE_BASE] = MODEL_OUTPUT_NEUTRAL,       // Hold zero during stance support.
      [MODEL_STANCE_GYRO] = MODEL_OUTPUT_NEUTRAL,
      [MODEL_STANCE_ACCEL] = MODEL_OUTPUT_NEUTRAL,
      [MODEL_PUSH_OFF] = MODEL_OUTPUT_DF,
      [MODEL_INIT_SWING] = MODEL_OUTPUT_DF,
      [MODEL_MID_SWING] = MODEL_OUTPUT_DF_FADE,         // Reduce support gradually at late Swing
    },
    [MODEL_STAIR_UP] = {
      [MODEL_FAILSAFE] = MODEL_OUTPUT_RELEASE,
      [MODEL_INIT_CONTACT] = MODEL_OUTPUT_RELEASE,
      [MODEL_STANCE_BASE] = MODEL_OUTPUT_RELEASE,
      [MODEL_STANCE_GYRO] = MODEL_OUTPUT_RELEASE,
      [MODEL_STANCE_ACCEL] = MODEL_OUTPUT_RELEASE,
      [MODEL_PUSH_OFF] = MODEL_OUTPUT_DF,
      [MODEL_INIT_SWING] = MODEL_OUTPUT_DF,
      [MODEL_MID_SWING] = MODEL_OUTPUT_DF_FADE,
    },
  };
  output = ModelTools_ActionFromTable(m, action_table);

  /* Stair-down between-flight override:
   * 1) the PUSH_OFF detector latches level-walk/turning evidence for this step,
   * 2) keep normal PF behavior unless the latch is active,
   * 3) swap only the two swing assist states to their DF equivalents.
   */
  if((m != NULL) &&
     (m->mode == MODEL_STAIR_DOWN) &&
     (m->stair_down_df_override_active))
  {
    if((m->state == MODEL_INIT_SWING)||(m->state == MODEL_MID_SWING))
    {
      output = MODEL_OUTPUT_RELEASE;
    }
  }

  /* LEVEL_WALK stance neutral toggle:
   * 1) action table keeps stance as NEUTRAL by default,
   * 2) operator flag can make stance behave like RELEASE without changing the FSM,
   * 3) limit the override to LEVEL_WALK stance states so stair modes stay unchanged.
   */
  if((m != NULL) &&
     (m->mode == MODEL_LEVEL_WALK) &&
     ((m->state == MODEL_STANCE_BASE) ||
      (m->state == MODEL_STANCE_GYRO) ||
      (m->state == MODEL_STANCE_ACCEL)) &&
     (!ModelTools_GetLevelStanceNeutralEnabled()))
  {
    output = MODEL_OUTPUT_RELEASE;
  }

  /* LEVEL_WALK PUSH_OFF release toggle flow:
   * 1) Evaluate the normal action table first for all mode/state combinations.
   * 2) Override only LEVEL_WALK+PUSH_OFF when release flag is enabled.
   * 3) Keep all other states/modes untouched so behavior matches existing models.
   */
  if((m != NULL) &&
     (m->mode == MODEL_LEVEL_WALK) &&
     (m->state == MODEL_PUSH_OFF) &&
     (ModelTools_GetLevelPushOffReleaseEnabled()))
  {
    output = MODEL_OUTPUT_RELEASE;
  }

  /* Stride-time guard output policy:
   * 1) apply this guard only in LEVEL_WALK mode,
   * 2) if recent step rhythm does not look like level walking, suppress assist by forcing RELEASE,
   * 3) stair modes bypass this guard and keep their table-selected outputs.
   */
  if((m != NULL) &&
     (m->mode == MODEL_LEVEL_WALK) &&
     (output != MODEL_OUTPUT_RELEASE) &&
     (output != MODEL_OUTPUT_NEUTRAL) &&
     !ModelTools_StrideGuardIsAssistAllowed())
  {
    output = MODEL_OUTPUT_RELEASE;
  }

  return output;
}
