export function previousCompletedPeriod(now = new Date()) {
  const period = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${period.getFullYear()}-${String(period.getMonth() + 1).padStart(2, "0")}`;
}
