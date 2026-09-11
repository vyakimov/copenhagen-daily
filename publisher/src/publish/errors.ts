export type PublisherFailure = Error & { type: string; details: Record<string, unknown> };

export function publisherError(
  type: string,
  message: string,
  details: Record<string, unknown> = {},
): PublisherFailure {
  return Object.assign(new Error(message), { type, details });
}
