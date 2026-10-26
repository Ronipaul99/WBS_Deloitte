function buildPdf(contentStream: Buffer): Buffer {
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${contentStream.length} >>\nstream\n${contentStream.toString('latin1')}\nendstream`,
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(pdf, 'latin1'));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = Buffer.byteLength(pdf, 'latin1');
  pdf += `xref\n0 ${objects.length + 1}\n`;
  pdf += '0000000000 65535 f \n';
  for (const offset of offsets.slice(1)) {
    pdf += `${offset.toString().padStart(10, '0')} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\n`;
  pdf += `startxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(pdf, 'latin1');
}

export function textPdfBuffer(): Buffer {
  return buildPdf(Buffer.from('BT /F1 12 Tf 72 720 Td (Synthetic project scope) Tj ET', 'ascii'));
}

export function scannedPdfBuffer(): Buffer {
  return buildPdf(Buffer.from(
    'q 10 0 0 10 72 720 cm BI /W 1 /H 1 /CS /RGB /BPC 8 ID \x00\x00\x00 EI Q',
    'latin1',
  ));
}
