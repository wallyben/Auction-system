import { describe, expect, it } from "vitest";
import { money } from "./api";

describe("money", () => {
  it("shows an unresolved amount as a dash", () => {
    expect(money(null)).toBe("—");
    expect(money("")).toBe("—");
  });

  it("formats euros without cents", () => {
    expect(money("18600")).toMatch(/18,600/);
  });
});
