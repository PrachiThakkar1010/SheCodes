PARAKH : SEE BEYOND THE LABEL

Parakh is a web-based system designed to analyze packaged-product labels using OCR, computer vision and a
rule-based compliance engine. It extracts declarations from product packaging, checks them against applicable
Legal Metrology requirements, and generates an understandable compliance report.

Project Overview
• Packaging analysis: accepts product-label images and checks whether the available packaging views are
sufficient.
• OCR extraction: extracts printed declarations such as product information, quantity, MRP, dates, batch details
and regulatory information.
• Computer vision: uses image processing and OCR bounding boxes to improve extraction and validate printed
information.
• Compliance engine: applies rule-based checks rather than relying only on an AI-generated decision.
• Nutrition analysis: extracts nutritional declarations and performs consistency checks.
• Report generation: presents compliance status, extracted information, violations and explanations.
• Complaint workflow: allows eligible logged-in users to file and track complaints for non-compliant products.
• History: stores previous scans and their compliance status for the user
• AI Assisstant for companies: Helps the companies to design legally compliant and appealing packaging.

Technology Stack
Layer                                                                        Technology
  Backend                                                                      Python, Django
  OCR                                                                          PaddleOCR / PaddlePaddle
  Image Processing                                                             OpenCV
  Compliance                                                                   Python rule-based compliance engine
  Database                                                                     PostgreSQL; Django ORM
  Frontend                                                                     HTML, CSS, JavaScript, Django Templates
  Static Files                                                                 Django static files / WhiteNoise
  Production                                                                   Server Gunicorn
  Deployment                                                                   Railway
