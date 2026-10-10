import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import en from "./en.json";
import fil from "./fil.json";
import { format, I18nProvider, pick, useI18n } from "./i18n";
import { LanguageToggle } from "./LanguageToggle";

function Probe() {
  const { t } = useI18n();
  return (
    <>
      <p>{t("nav.dashboard")}</p>
      <LanguageToggle />
    </>
  );
}

describe("i18n", () => {
  it("has a Filipino string for every English key", () => {
    expect(Object.keys(fil).sort()).toEqual(Object.keys(en).sort());
  });

  it("fills variables and falls back to English, then to the key", () => {
    expect(format({ a: "Hi {name}" }, {}, "a", { name: "Ana" })).toBe("Hi Ana");
    expect(format({}, { b: "English only" }, "b")).toBe("English only");
    expect(format({}, {}, "missing.key")).toBe("missing.key");
  });

  it("picks form labels with an English fallback", () => {
    expect(pick({ en: "Weight", fil: "Timbang" }, "fil")).toBe("Timbang");
    expect(pick({ en: "Weight" }, "fil")).toBe("Weight");
  });

  it("switches language and remembers the choice", async () => {
    const user = userEvent.setup();
    render(<I18nProvider><Probe /></I18nProvider>);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "FIL" }));
    expect(screen.getByText("Pangkalahatang-tanaw")).toBeInTheDocument();
    expect(localStorage.getItem("gk.lang")).toBe("fil");
  });
});
