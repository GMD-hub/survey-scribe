from extractors.pdf import pdf_to_markdown, is_scanned_pdf
from pathlib import Path

pdf = Path("tests/samples/final_interview_HBS_2014.pdf")

print("Is scanned:", is_scanned_pdf(pdf))

md = pdf_to_markdown(pdf)
print(md[:3000])   

# Chunking code
# is_scanned, chunks = process_pdf(pdf)
# print(f"Is scanned: {is_scanned}")
# print(f"Number of chunks: {len(chunks)}")