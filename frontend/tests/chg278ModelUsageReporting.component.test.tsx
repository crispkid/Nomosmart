import { describe, expect, it } from "vitest";

import { formatReportCell } from "@/lib/reportFormatting";
import { getReportHeaders } from "@/lib/reportExport";


describe("CHG-278 model usage reporting", () => {
  it("formats values by field meaning instead of numeric magnitude", () => {
    expect(formatReportCell("call_count", 17058, "zh", "未提供")).toBe("17,058");
    expect(formatReportCell("avg_latency_ms", 6224.86, "zh", "未提供")).toBe("6,224.86");
    expect(formatReportCell("estimated_cost", 0.0042168, "zh", "未提供")).toBe("0.0042168");
    expect(formatReportCell("error_rate", 0, "zh", "未提供")).toBe("0%");
    expect(formatReportCell("error_rate", 0.66667, "en", "Not provided")).toBe("66.67%");
    expect(formatReportCell("provider_reported_cost", null, "en", "Not provided")).toBe("Not provided");
    expect(formatReportCell("provider_reported_cost", 0, "en", "Not provided")).toBe("0");
  });

  it("exports the local AI model name and no provider/client/key identity", () => {
    const headers = getReportHeaders([], "model_usage_metrics");
    expect(headers).toContain("ai_model_name");
    expect(headers).not.toContain("model_name");
    expect(headers).not.toContain("integration_client_id");
    expect(headers).not.toContain("api_key_prefix");
  });
});
