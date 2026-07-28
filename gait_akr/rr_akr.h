#ifndef RR_AKR_H
#define RR_AKR_H

#include <stdbool.h>
#include <stdint.h>

#include "runtime/app_config.h"
#include "modes/gait/model_types.h"
#include "sensing/signal.h"

#ifndef RR_AKR_LOOP_PERIOD_MS
#define RR_AKR_LOOP_PERIOD_MS APP_CFG_CONTROL_LOOP_PERIOD_MS
#endif

typedef struct RR_AKR_MoveParams
{
  float torque;
  float angle;
  float speed;
  float kp;
  float kd;
} RR_AKR_MoveParams;

typedef enum RR_AKR_GaitModel
{
  RR_AKR_GAIT_MODEL_UPDATE = 0,
  RR_AKR_GAIT_MODEL_TEST = 1,
  RR_AKR_GAIT_MODEL_END = 2
} RR_AKR_GaitModel;

typedef struct RR_AKR_WalkSample
{
  uint32_t sequence;
  uint32_t timestamp_ms;
  float gyro_z_dps;
  float tilt_forward_deg;
  uint8_t gait_state;
  uint8_t terrain;
} RR_AKR_WalkSample;

extern Signal g_rr_akr_sig;
extern Model g_rr_akr_gait;
extern uint32_t g_rr_akr_last_ms;
extern bool g_rr_akr_inited;

void RR_AKR_ResetMoveParamsDefaults(void);
bool RR_AKR_GetMoveParams(ModelOutput out, RR_AKR_MoveParams *params_out);
bool RR_AKR_SetMoveParams(ModelOutput out, const RR_AKR_MoveParams *params);
void RR_AKR_ApplyModelOutput(ModelOutput out, bool force);
void RR_AKR_Init(void);
void RR_AKR_ModeEnter(void);
void RR_AKR_ModeExit(void);
void RR_AKR_Loop(void);
bool RR_AKR_LoadMoveParams(void);
bool RR_AKR_SaveMoveParams(void);
bool RR_AKR_SetAssistLevelPct(float assist_pct);
bool RR_AKR_GetAssistLevelPct(float *assist_pct_out);
bool RR_AKR_IsImuOk(void);
void RR_AKR_NotifyImuUpdated(uint32_t now_ms);
uint32_t RR_AKR_GetLastImuUpdateMs(void);
uint32_t RR_AKR_GetLastStepMs(void);
bool RR_AKR_SetWalkMode(ModelMode walk_mode);
ModelMode RR_AKR_GetWalkMode(void);
ModelOutput RR_AKR_GetLastOutput(void);
bool RR_AKR_SetGaitModel(RR_AKR_GaitModel gait_model);
bool RR_AKR_SetGaitModelByName(const char *name);
RR_AKR_GaitModel RR_AKR_GetGaitModel(void);
const char *RR_AKR_GetGaitModelName(void);
RR_AKR_GaitModel RR_AKR_GetRequiredGaitModel(void);
bool RR_AKR_GetLatestWalkSample(RR_AKR_WalkSample *sample_out);

#endif
