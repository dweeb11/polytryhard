import type { paths } from './types';

type JsonBody<R> = R extends { content: { 'application/json': infer T } } ? T : never;

type GetResponses<P extends keyof paths> = paths[P] extends { get: { responses: infer R } }
	? R
	: never;

type GetOkResponse<R> = R extends { 200: infer Ok } ? JsonBody<Ok> : never;

/** 200 JSON body for a documented GET path (static paths only). */
export type ApiGetResponse<P extends keyof paths> = GetOkResponse<GetResponses<P>>;
