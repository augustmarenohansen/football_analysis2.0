from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from PIL import Image
from reportlab.lib.utils import ImageReader
pdfmetrics.registerFont(TTFont('Arial','/System/Library/Fonts/Supplemental/Arial.ttf'))
pdfmetrics.registerFont(TTFont('ArialBold','/System/Library/Fonts/Supplemental/Arial Bold.ttf'))
W,H=595.5,842.25
c=canvas.Canvas('output/pdf/August_Mareno_Hansen_CV_oppdatert.pdf',pagesize=(W,H))
c.setTitle('August Mareno Hansen - CV')
c.setAuthor('August Mareno Hansen')
navy=HexColor('#323c4d'); grey=HexColor('#e5e5e5')
c.setFillColor(white);c.rect(0,0,W,H,fill=1,stroke=0)
c.setFillColor(grey);c.rect(0,0,184,H,fill=1,stroke=0)
c.setFillColor(navy);c.rect(0,H-141,W,141,fill=1,stroke=0)
im=Image.open('tmp/pdfs/original-hi.png'); im=im.crop((40,107,342,409))
c.drawImage(ImageReader(im),20,H-204,151,151)
c.setFillColor(white);c.setFont('ArialBold',23);c.drawString(201,H-70,'AUGUST MARENO HANSEN')
c.setFont('Arial',11);c.drawString(202,H-96,'MASTERSTUDENT I DATATEKNOLOGI')
def para(txt,x,t,w,size=9.6,bold=False,leading=None):
 st=ParagraphStyle('p',fontName='ArialBold' if bold else 'Arial',fontSize=size,leading=leading or size*1.32,textColor=navy)
 p=Paragraph(txt,st); pw,ph=p.wrap(w,700);p.drawOn(c,x,H-t-ph);return t+ph

def sh(txt,t):
 para(txt,20,t,144,13.5,True)
 c.setStrokeColor(navy);c.setLineWidth(1.4);c.line(20,H-t-23,164,H-t-23)
 return t+29

y=sh('KONTAKT',219)
y=para('+47 482 71 444',20,y,152,10)+6
y=para('august.m.hansen@gmail.com',20,y,154,8.7)+6
y=para('Klokkerveien 15<br/>8074 Bodø, Norge',20,y,148,9.6)+14
y=sh('FERDIGHETER',y)
for skill in ['JavaScript','Java','Python','C#','Semantic Kernel','Azure','HTML/CSS','Teamarbeid','Problemløsning']:
 y=para('•  '+skill,20,y,145,9.6,leading=13)
y+=12
y=sh('SPRÅK',y)
for language in ['Norsk','Engelsk','Spansk (grunnleggende)']:
 y=para('•  '+language,20,y,145,9.6,leading=13)
y+=14
y=sh('UTDANNING',y)
y=para('NTNU',20,y,145,10.5,True)+3
y=para('Master i datateknologi',20,y,145,9.6,True)+3
y=para('Trondheim, Norge<br/>Aug. 2026 - nå | Heltid',20,y,145,9.2)+5
y=para('Spesialisering i programvaresystemer.<br/>Første studieår.<br/>Forventet fullført juni 2028.',20,y,145,9.2)+12
y=para('Høgskulen på Vestlandet',20,y,145,9.8,True)+3
y=para('Bachelor i dataingeniør',20,y,145,9.6,True)+3
y=para('Bergen, Norge<br/>Aug. 2023 - juni 2026<br/>Heltid | Fullført grad',20,y,145,9.2)
assert y<822, y
print('sidebar bottom',y)
x=237; width=328
# Timeline and section circles echo the original design.
c.setStrokeColor(navy);c.setLineWidth(.7);c.line(209,H-184,209,H-787)
def section(title,t,symbol):
 c.setFillColor(navy);c.circle(209,H-t-9,10,fill=1,stroke=0)
 c.setStrokeColor(white);c.setLineWidth(1.2)
 c.roundRect(203,H-t-13,12,8,1,fill=0,stroke=1)
 c.roundRect(206,H-t-5,6,3,1,fill=0,stroke=1)
 c.line(203,H-t-8,215,H-t-8)
 para(title,x,t,width,14,True)
 c.setStrokeColor(navy);c.setLineWidth(1);c.line(x,H-t-23,x+width,H-t-23)
 return t+29

def job(title,meta,desc,t):
 t=para(title,x,t,width,10.8,True)+4
 t=para(meta,x,t,width,9.1)+6
 t=para(desc,x,t,width,9.7)+16
 return t

y=section('ARBEIDSERFARING',178,'A')
y=job('Utvikler (sommerintern) | DIPS','Bodø, Norge | Juni - juli 2026 | Heltid (100 %)',
 'Sommerkontrakt. Bidro til utvikling og modernisering av et system for pasientinnsjekking ved sykehus.',y)
y=job('Badevakt / driftsassistent | Bergen kommune','Bergen, Norge | Des. 2025 - juni 2026 | Tilkallingsvikar',
 'Arbeidet som tilkallingsvikar ved et kommunalt svømmeanlegg.',y)
y=job('Servicemedarbeider | Bodø kommune','Bodø, Norge | Sommersesongene 2020-2025 | Heltid (100 %)',
 'Sesongarbeid med varierende antall uker i juni-august hvert år. Utførte vaktmesteroppgaver ved sykehjem, inkludert gressklipping, maling og generelt vedlikehold av kommunale bygg.',y)
y=job('Butikkmedarbeider | KIWI','Bodø, Norge | Feb. 2023 - juni 2024 | Deltid (40 %)',
 'Kundebehandling, varepåfylling, kassearbeid og generelle butikkoppgaver.',y)
y+=5
y=section('BACHELORPROSJEKT',y,'P')
y=job('Bacheloroppgave for Mowi','Jan. - juni 2026 | Skribent og utvikler',
 'Utvikling av en plattform for salgsanalyse i sanntid og prognoser for laksepriser.',y)
y+=5
y=section('ANNEN ERFARING',y,'E')
y=job('Jobbskygging | itslearning','Okt. 2025 | Én uke',
 'Deltok i et jobbskyggingsprogram og ga tilbakemeldinger og forslag til forbedringer av selskapets applikasjon.',y)
print('main bottom',y)
assert y<820
c.save()
