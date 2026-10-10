import { downloadFile, readText, toCsv } from "./download";

describe("downloads", () => {
  it("quotes CSV cells that need it", () => {
    expect(toCsv([["Item", "Note"], ["ORS", 'says "hi", ok'], ["Gauze", null]])).toBe(
      'Item,Note\r\nORS,"says ""hi"", ok"\r\nGauze,\r\n',
    );
  });

  it("downloads text as a file", async () => {
    downloadFile("a.csv", "x,y\r\n", "text/csv");
    const blob = (URL.createObjectURL as ReturnType<typeof vi.fn>).mock.calls[0][0] as Blob;
    expect(await readText(blob)).toBe("x,y\r\n");
  });
});
