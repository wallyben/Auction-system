import { describe, expect, it } from "vitest";
import { money } from "./api";

describe("money", () => {
  it("shows an unresolved amount as a dash", () => {
    expect(money(null)).toBe("NOT YET KNOWN");
    expect(money("")).toBe("NOT YET KNOWN");
  });

  it("formats euros without cents", () => {
    expect(money("18600")).toMatch(/18,600/);
  });
});
