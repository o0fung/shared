#ifndef MODEL_TEST_H
#define MODEL_TEST_H

#ifdef __cplusplus
extern "C" {
#endif

#include "modes/gait/model_types.h"

ModelState ModelTest_EventDetection(Model *m, float delta_t_us);
ModelOutput ModelTest_Action(const Model *m);

#ifdef __cplusplus
}
#endif

#endif /* MODEL_TEST_H */
