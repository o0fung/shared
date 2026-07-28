#ifndef MODEL_UPDATE_H
#define MODEL_UPDATE_H

#ifdef __cplusplus
extern "C" {
#endif

#include "modes/gait/model_types.h"

ModelState ModelUpdate_EventDetection(Model *m, float delta_t_us);
ModelOutput ModelUpdate_Action(const Model *m);

#ifdef __cplusplus
}
#endif

#endif /* MODEL_UPDATE_H */
