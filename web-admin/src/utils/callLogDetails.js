export async function loadCallLogDetail(id, fetchDetail, cache) {
  if (cache.has(id)) return cache.get(id);
  const detail = await fetchDetail(id);
  cache.set(id, detail);
  return detail;
}
