import type { MonitorConfig } from "./parser";

export function generateMonitor(config: MonitorConfig): string {
  const channels = JSON.stringify(config.notifyChannels);
  const imports = ["Monitor", "navigate", "extract_text", "get_last_value", "set_value", "notify"];
  if (config.recordToInflux) imports.push("record_metric");

  const importLine = "from app.helpers import " + imports.join(", ");

  let checkBody = "";
  if (config.waitForNetworkIdle) {
    checkBody += "    await page.wait_for_load_state(\"networkidle\")\n";
  }
  checkBody += `    value = await extract_text(page, ${JSON.stringify(config.selector)})\n`;
  checkBody += `    prev = await get_last_value(ctx.db, ${JSON.stringify(config.name)})\n`;
  checkBody += `    await set_value(ctx.db, ${JSON.stringify(config.name)}, value)\n`;
  if (config.notifyChannels.length > 0) {
    checkBody += `    if prev is not None and value != prev and ctx.apprise:\n`;
    checkBody += `        await notify(ctx.apprise, title=${JSON.stringify(config.name + " changed")}, body=value, tags=${channels})\n`;
  }
  if (config.recordToInflux) {
    checkBody += `    if ctx.influx:\n`;
    checkBody += `        await record_metric(ctx.influx, ${JSON.stringify(config.name)}, value)\n`;
  }

  return [
    importLine,
    "",
    "monitor = Monitor(",
    `    name=${JSON.stringify(config.name)},`,
    `    schedule=${JSON.stringify(config.schedule)},`,
    `    url=${JSON.stringify(config.url)},`,
    `    notify_channels=${channels},`,
    ")",
    "",
    "@monitor.check",
    "async def check(page, ctx):",
    `    await navigate(page, ${JSON.stringify(config.url)})`,
    checkBody.trimEnd(),
  ].join("\n") + "\n";
}
