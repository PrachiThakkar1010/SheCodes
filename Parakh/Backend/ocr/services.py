import pytesseract
from PIL import Image
from products.models import ExtractedLabelData
# On Windows, specify tesseract path if not in system PATH:
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
def process_image_ocr(scan_instance):
 """Extracts text from the uploaded product image."""
 image_path = scan_instance.image.path
 img = Image.open(image_path)

 extracted_text = pytesseract.image_to_string(img)

 # Save extracted text to ExtractedLabelData
 label_data, created = ExtractedLabelData.objects.get_or_create(
 scan=scan_instance,
 defaults={'raw_ocr_text': extracted_text}
 )
 if not created:
 label_data.raw_ocr_text = extracted_text
 label_data.save()

 return extracted_text