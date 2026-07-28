#ifndef MODEL_TOOLS_H
#define MODEL_TOOLS_H

#ifdef __cplusplus
extern "C" {
#endif

#include "modes/gait/model_types.h"
#include "sensing/signal.h"

void ModelTools_Init(Model *m);
void ModelTools_SetMode(Model *m, ModelMode mode);
ModelMode ModelTools_GetMode(const Model *m);
ModelState ModelTools_GetState(const Model *m);

float ModelTools_Gyro(const Model *m, int idx);
float ModelTools_Accel(const Model *m, int idx);
bool ModelTools_GyroIncreasing(const Model *m);
bool ModelTools_AccelIncreasing(const Model *m);
bool ModelTools_GyroOverLevel(const Model *m, int idx);
bool ModelTools_AccelOverLevel(const Model *m, int idx);
bool ModelTools_GyroSlopeFlipUp(const Model *m);
bool ModelTools_GyroSlopeFlipDown(const Model *m);
bool ModelTools_AccelSlopeFlipUp(const Model *m);
bool ModelTools_AccelSlopeFlipDown(const Model *m);
bool ModelTools_IsForwardTiltInRange(const Model *m);
float ModelTools_EventDetectTiltAbsMaxDeg(ModelMode mode);
bool ModelTools_IsAbsTiltWithinLimit(const Model *m, float tilt_abs_max_deg);
void ModelTools_SetTiltFailsafeEnabled(bool enabled);
bool ModelTools_GetTiltFailsafeEnabled(void);
void ModelTools_SetLevelPushOffReleaseEnabled(bool enabled);
bool ModelTools_GetLevelPushOffReleaseEnabled(void);
void ModelTools_SetLevelStanceNeutralEnabled(bool enabled);
bool ModelTools_GetLevelStanceNeutralEnabled(void);
void ModelTools_SetStrideGuardEnabled(bool enabled);
bool ModelTools_GetStrideGuardEnabled(void);
void ModelTools_StrideGuardReset(void);
void ModelTools_StrideGuardOnPushOff(void);
bool ModelTools_StrideGuardIsAssistAllowed(void);
float ModelTools_StrideGuardGetLastStrideMs(void);
float ModelTools_StrideGuardGetEstimatedTypicalStrideMs(void);
float ModelTools_StrideGuardGetDynamicMaxMs(void);

void ModelTools_TimerStep(Model *m, float dt_us);
bool ModelTools_TimerElapsed(const Model *m);
void ModelTools_TimerReset(Model *m);
void ModelTools_TimerAlignToTime(Model *m, float ref_t_ms);
float ModelTools_ClampThresholdMs(float threshold_ms);
void ModelTools_EnterFailsafe(Model *m);

int8_t ModelTools_PolarityHyst(int8_t prev_pol, float cur_value);
bool ModelTools_IsPosGyroPol(const Model *m, int idx);
bool ModelTools_IsPosAccelPol(const Model *m, int idx);
bool ModelTools_IsRawPosGyro(const Model *m, int idx, float threshold_dps);
bool ModelTools_IsRawPosAccel(const Model *m, int idx, float threshold_g);
bool ModelTools_IsRawNegAccel(const Model *m, int idx, float threshold_g);
bool ModelTools_IsNegGyroPol(const Model *m, int idx);
bool ModelTools_IsNegAccelPol(const Model *m, int idx);
int8_t ModelTools_GyroSlopeSign(const Model *m, int idx);
int8_t ModelTools_AccelSlopeSign(const Model *m, int idx);

void ModelTools_HistReset(Model *m);
void ModelTools_HistPush(Model *m);

typedef enum ModelPushOffPeakState
{
  MODEL_PUSH_OFF_PEAK_NONE = 0,
  MODEL_PUSH_OFF_PEAK_GYRO_ONLY = 1,
  MODEL_PUSH_OFF_PEAK_ACCEL_ONLY = 2,
  MODEL_PUSH_OFF_PEAK_PAIRED = 3
} ModelPushOffPeakState;

bool ModelTools_DetectGyroPosPeak(Model *m);
bool ModelTools_DetectGyroNegValley(Model *m);
bool ModelTools_DetectGyroInitContactValley(Model *m);
bool ModelTools_DetectAccelPosPeak(Model *m);
bool ModelTools_DetectAccelNegValley(Model *m);
ModelPushOffPeakState ModelTools_DetectPushOffPeakPair(Model *m);
bool ModelTools_DetectAccelInitContactValley(Model *m);
float ModelTools_ForwardTiltAccOnlyDeg(const Signal *sig);
void ModelTools_UpdateSignal(Model *m, const Signal *sig);
ModelOutput ModelTools_ActionFromTable(const Model *m,
                                       const ModelOutput action_table[MODEL_MODE_COUNT][MODEL_STATE_COUNT]);

#ifdef __cplusplus
}
#endif

#endif /* MODEL_TOOLS_H */
