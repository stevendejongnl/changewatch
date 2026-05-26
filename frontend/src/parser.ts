export interface MonitorConfig {
  name: string;
  schedule: string;
  url: string;
  selector: string;
  notifyChannels: string[];
  recordToInflux: boolean;
  waitForNetworkIdle: boolean;
}

export function parseMonitor(source: string): MonitorConfig | null {
  // Strip comment lines before parsing (same as Python version)
  const lines = source.split("\n").filter(l => !l.trim().startsWith("#"));
  const src = lines.join("\n");

  const nameMatch = src.match(/\bname\s*=\s*["']([^"']+)["']/);
  const scheduleMatch = src.match(/\bschedule\s*=\s*["']([^"']+)["']/);

  if (!nameMatch || !scheduleMatch) return null;

  const urlMatch = src.match(/\burl\s*=\s*["']([^"']+)["']/);
  const selectorMatch = src.match(/extract_text\s*\(\s*page\s*,\s*["']([^"']+)["']/);

  // Parse notify_channels list
  const channelsMatch = src.match(/notify_channels\s*=\s*\[([^\]]*)\]/);
  let notifyChannels: string[] = [];
  if (channelsMatch) {
    notifyChannels = [...channelsMatch[1].matchAll(/["']([^"']+)["']/g)].map(m => m[1]);
  }

  return {
    name: nameMatch[1],
    schedule: scheduleMatch[1],
    url: urlMatch ? urlMatch[1] : "",
    selector: selectorMatch ? selectorMatch[1] : "",
    notifyChannels,
    recordToInflux: src.includes("record_metric("),
    waitForNetworkIdle: src.includes('wait_for_load_state("networkidle")') ||
                        src.includes("wait_for_load_state('networkidle')"),
  };
}
