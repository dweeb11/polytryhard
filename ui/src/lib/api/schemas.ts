/**
 * Friendly aliases for OpenAPI component schemas.
 * Source of truth: ui/openapi/openapi.json → ui/src/lib/api/types.ts
 */
import type { components } from './types';

type Schemas = components['schemas'];

export type ApiAuditEvent = Schemas['AuditEvent'];
export type ApiCalibrationBin = Schemas['CalibrationBin'];
export type ApiCashEvent = Schemas['CashEvent'];
export type ApiCashEventKind = Schemas['CashEventKind'];
export type ApiEvalRosterEntry = Schemas['EvalRosterEntry'];
export type ApiEvalSnapshot = Schemas['EvalSnapshot'];
export type ApiPaperPositionRecord = Schemas['PaperPositionRecord'];
export type ApiSignalOutcome = Schemas['SignalOutcome'];
export type ApiSignalRecord = Schemas['SignalRecord'];
export type ApiSourceHealthEntry = Schemas['SourceHealthEntry'];
export type ApiStrategyEval = Schemas['StrategyEval'];
export type ApiStrategyInstance = Schemas['StrategyInstance'];
export type ApiStrategyState = Schemas['StrategyState'];
export type ApiSystemEnvState = Schemas['SystemEnvState'];
export type ApiSystemState = Schemas['SystemState'];
export type ApiPositionSide = Schemas['PositionSide'];
