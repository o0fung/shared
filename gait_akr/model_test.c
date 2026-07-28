#include "modes/gait/model_test.h"
#include "modes/gait/model_tools.h"

ModelState ModelTest_EventDetection(Model *m, float delta_t_us)
{
  ModelState next_state = MODEL_FAILSAFE;

  if(m == NULL)
  {
    return MODEL_FAILSAFE;
  }

  ModelTools_TimerStep(m, delta_t_us);
  // Each loop records the newest gyro sample first, so all checks use current motion.
  ModelTools_HistPush(m);

  switch(m->state)
  {
    case MODEL_FAILSAFE:
    default:
      break;
  }

  next_state = m->state;
  return next_state;
}

ModelOutput ModelTest_Action(const Model *m)
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
      [MODEL_INIT_SWING] = MODEL_OUTPUT_RELEASE,
      [MODEL_MID_SWING] = MODEL_OUTPUT_RELEASE,
    },
    [MODEL_LEVEL_WALK] = {
      [MODEL_FAILSAFE] = MODEL_OUTPUT_RELEASE,
      [MODEL_INIT_CONTACT] = MODEL_OUTPUT_RELEASE,
      [MODEL_STANCE_BASE] = MODEL_OUTPUT_RELEASE,
      [MODEL_STANCE_GYRO] = MODEL_OUTPUT_RELEASE,
      [MODEL_STANCE_ACCEL] = MODEL_OUTPUT_RELEASE,
      [MODEL_PUSH_OFF] = MODEL_OUTPUT_RELEASE,
      [MODEL_INIT_SWING] = MODEL_OUTPUT_RELEASE,
      [MODEL_MID_SWING] = MODEL_OUTPUT_RELEASE,
    },
    [MODEL_STAIR_UP] = {
      [MODEL_FAILSAFE] = MODEL_OUTPUT_RELEASE,
      [MODEL_INIT_CONTACT] = MODEL_OUTPUT_RELEASE,
      [MODEL_STANCE_BASE] = MODEL_OUTPUT_RELEASE,
      [MODEL_STANCE_GYRO] = MODEL_OUTPUT_RELEASE,
      [MODEL_STANCE_ACCEL] = MODEL_OUTPUT_RELEASE,
      [MODEL_PUSH_OFF] = MODEL_OUTPUT_RELEASE,
      [MODEL_INIT_SWING] = MODEL_OUTPUT_RELEASE,
      [MODEL_MID_SWING] = MODEL_OUTPUT_RELEASE,
    },
  };
  output = ModelTools_ActionFromTable(m, action_table);

  return output;
}
