#ifndef MODEL_TYPES_H
#define MODEL_TYPES_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "runtime/app_config.h"

typedef enum ModelState
{
  MODEL_FAILSAFE = 0,
  MODEL_INIT_CONTACT = 1,
  MODEL_STANCE_BASE = 2,
  MODEL_STANCE_GYRO = 3,
  MODEL_STANCE_ACCEL = 4,
  MODEL_PUSH_OFF = 5,
  MODEL_INIT_SWING = 6,
  MODEL_MID_SWING = 7,
  MODEL_STATE_END = 8
} ModelState;

#define MODEL_STATE_COUNT ((int)MODEL_STATE_END)

typedef enum ModelMode
{
  MODEL_STAIR_DOWN = 0,
  MODEL_LEVEL_WALK = 1,
  MODEL_STAIR_UP = 2,
  MODEL_MODE_END = 3
} ModelMode;

#define MODEL_MODE_COUNT ((int)MODEL_MODE_END)

typedef enum ModelOutput
{
  MODEL_OUTPUT_RELEASE = 0,
  MODEL_OUTPUT_DF = 1,
  MODEL_OUTPUT_PF = 2,
  MODEL_OUTPUT_DF_FADE = 3,
  MODEL_OUTPUT_PF_FADE = 4,
  MODEL_OUTPUT_PUSH_OFF = 5,
  MODEL_OUTPUT_NEUTRAL = 6,
  MODEL_OUTPUT_END = 7
} ModelOutput;

#define MODEL_OUTPUT_COUNT ((int)MODEL_OUTPUT_END)

typedef struct Model
{
  // Sign-corrected gyro history [0]=cur, [1]=prev, [2]=prev2.
  float gyro[3];
  // Raw filtered gyr_y history in deg/s [0]=cur, [1]=prev, [2]=prev2.
  float raw_gyro_y_dps[3];
  // Direct vertical acc.y history in g [0]=cur, [1]=prev, [2]=prev2.
  float accel[3];
  // Sign-corrected forward tilt [0]=cur, [1]=prev.
  float tilt_forward[2];

  // Polarity with hysteresis [-1,0,+1], [0]=cur, [1]=prev.
  int8_t gyro_pol[2];
  // Accel polarity with hysteresis [-1,0,+1], [0]=cur, [1]=prev.
  int8_t accel_pol[2];
  // Gyro slope sign [-1,0,+1], [0]=cur, [1]=prev.
  int8_t gyro_slope_sign[2];
  // Accel slope sign [-1,0,+1], [0]=cur, [1]=prev.
  int8_t accel_slope_sign[2];

  float t_ms;

  // Windowed history used by peak/valley detection.
  float gyro_hist_dps[APP_CFG_MODEL_GYRO_HIST_LEN];
  int8_t gyro_hist_pol[APP_CFG_MODEL_GYRO_HIST_LEN];
  int8_t gyro_slope_hist_sign[APP_CFG_MODEL_GYRO_HIST_LEN];
  int8_t accel_slope_hist_sign[APP_CFG_MODEL_GYRO_HIST_LEN];
  float gyro_hist_t_ms[APP_CFG_MODEL_GYRO_HIST_LEN];
  // Centered vertical acc.y history in g (acc.y - baseline).
  float accel_hist_g[APP_CFG_MODEL_GYRO_HIST_LEN];
  int8_t accel_hist_pol[APP_CFG_MODEL_GYRO_HIST_LEN];
  float accel_hist_t_ms[APP_CFG_MODEL_GYRO_HIST_LEN];
  uint8_t gyro_hist_head;
  uint8_t gyro_hist_count;

  float last_pos_peak_t_ms;
  float last_neg_valley_t_ms;
  float last_init_contact_valley_t_ms;
  float last_accel_pos_peak_t_ms;
  float last_accel_neg_valley_t_ms;
  float last_accel_init_contact_valley_t_ms;

  float gyro_dt_ms;
  float thresh_time_ms;
  bool init_contact_valley_seen;
  bool stair_down_df_override_active;
  bool stair_down_level_between_stairs_seen;

  ModelState state;
  ModelMode mode;
} Model;

#ifdef __cplusplus
}
#endif

#endif /* MODEL_TYPES_H */
