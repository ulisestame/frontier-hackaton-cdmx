"""Occupation -> sector generalization (quasi-identifier breaking).

Each line of OCCUPATIONS_SPEC is "sector: form | form | ...". A form "x/y" lists the
masculine and feminine variants; a form without "/" is invariable. Sector phrases follow
the style of the reference output ("profesional de medios", "profesional del transporte").
"""

SECTOR_PHRASES: dict[str, tuple[str, str]] = {
    # sector key: (masculine/neutral phrase, feminine phrase)
    "salud": ("profesional de la salud", "profesional de la salud"),
    "transporte": ("profesional del transporte", "profesional del transporte"),
    "medios": ("profesional de medios", "profesional de medios"),
    "creativas": ("profesional de las industrias creativas", "profesional de las industrias creativas"),
    "servicios": ("profesional de servicios", "profesional de servicios"),
    "educacion": ("profesional de la educación", "profesional de la educación"),
    "derecho": ("profesional del derecho", "profesional del derecho"),
    "finanzas": ("profesional de finanzas", "profesional de finanzas"),
    "tecnologia": ("profesional de tecnología", "profesional de tecnología"),
    "comercio": ("profesional del comercio", "profesional del comercio"),
    "agro": ("trabajador del sector agropecuario", "trabajadora del sector agropecuario"),
    "construccion": ("profesional de la construcción", "profesional de la construcción"),
    "gastronomia": ("profesional de la gastronomía", "profesional de la gastronomía"),
    "seguridad": ("profesional de la seguridad", "profesional de la seguridad"),
    "publico": ("profesional del sector público", "profesional del sector público"),
    "industria": ("profesional de la industria", "profesional de la industria"),
    "ingenieria": ("profesional de la ingeniería", "profesional de la ingeniería"),
    "deporte": ("profesional del deporte", "profesional del deporte"),
    "ciencia": ("profesional de la ciencia", "profesional de la ciencia"),
    "estudiante": ("estudiante de educación superior", "estudiante de educación superior"),
    "hogar": ("persona dedicada al hogar", "persona dedicada al hogar"),
    "pensionado": ("persona pensionada", "persona pensionada"),
    "independiente": ("trabajador independiente", "trabajadora independiente"),
}

SECTOR_PHRASES_EN: dict[str, str] = {
    "salud": "healthcare professional", "transporte": "transportation professional",
    "medios": "media professional", "creativas": "creative industries professional",
    "servicios": "services professional", "educacion": "education professional",
    "derecho": "legal professional", "finanzas": "finance professional",
    "tecnologia": "technology professional", "comercio": "retail professional",
    "agro": "agricultural worker", "construccion": "construction professional",
    "gastronomia": "food service professional", "seguridad": "security professional",
    "publico": "public sector professional", "industria": "industry professional",
    "ingenieria": "engineering professional", "deporte": "sports professional",
    "ciencia": "science professional", "estudiante": "university student",
    "hogar": "homemaker", "pensionado": "retiree", "independiente": "independent worker",
}

DEFAULT_SECTOR = "independiente"

OCCUPATIONS_SPEC = """
salud: médico/médica | enfermero/enfermera | enfermero jefe/enfermera jefe | auxiliar de enfermería
salud: odontólogo/odontóloga | psicólogo/psicóloga | fisioterapeuta | nutricionista | terapeuta
salud: terapeuta ocupacional | terapeuta respiratorio/terapeuta respiratoria | optómetra
salud: bacteriólogo/bacterióloga | fonoaudiólogo/fonoaudióloga | veterinario/veterinaria
salud: médico veterinario/médica veterinaria | cirujano/cirujana | pediatra | psiquiatra
salud: ginecólogo/ginecóloga | cardiólogo/cardióloga | dermatólogo/dermatóloga
salud: anestesiólogo/anestesióloga | radiólogo/radióloga | paramédico/paramédica
salud: instrumentador quirúrgico/instrumentadora quirúrgica | químico farmacéutico/química farmacéutica
salud: regente de farmacia | farmaceuta | higienista oral | médico general/médica general
salud: gerontólogo/gerontóloga | quiropráctico/quiropráctica | auxiliar de odontología
salud: auxiliar de farmacia | médico cirujano/médica cirujana | neurólogo/neuróloga | oftalmólogo/oftalmóloga
educacion: docente | profesor/profesora | maestro/maestra | rector/rectora | licenciado/licenciada
educacion: pedagogo/pedagoga | educador/educadora | tutor/tutora | catedrático/catedrática
educacion: docente universitario/docente universitaria | profesor universitario/profesora universitaria
educacion: orientador escolar/orientadora escolar | educador infantil/educadora infantil
educacion: profesor de inglés/profesora de inglés | docente de primaria | docente de bachillerato
derecho: abogado/abogada | abogado litigante/abogada litigante | juez/jueza | notario/notaria
derecho: litigante | procurador/procuradora | asesor jurídico/asesora jurídica | jurista
derecho: conciliador/conciliadora | magistrado/magistrada | defensor público/defensora pública
derecho: secretario de juzgado/secretaria de juzgado | abogado laboralista/abogada laboralista
finanzas: contador/contadora | contador público/contadora pública | auxiliar contable
finanzas: revisor fiscal/revisora fiscal | economista | analista financiero/analista financiera
finanzas: asesor financiero/asesora financiera | tesorero/tesorera | auditor/auditora
finanzas: actuario/actuaria | corredor de bolsa/corredora de bolsa | trader | banquero/banquera
finanzas: cajero bancario/cajera bancaria | financista | asesor de seguros/asesora de seguros
finanzas: corredor de seguros/corredora de seguros | administrador financiero/administradora financiera
finanzas: auxiliar de contabilidad | analista de crédito | asistente contable
tecnologia: ingeniero de sistemas/ingeniera de sistemas | ingeniero de software/ingeniera de software
tecnologia: desarrollador/desarrolladora | programador/programadora | analista de sistemas
tecnologia: técnico en sistemas/técnica en sistemas | tecnólogo en sistemas/tecnóloga en sistemas
tecnologia: científico de datos/científica de datos | ingeniero electrónico/ingeniera electrónica
tecnologia: ingeniero de telecomunicaciones/ingeniera de telecomunicaciones
tecnologia: administrador de redes/administradora de redes | diseñador web/diseñadora web
tecnologia: desarrollador web/desarrolladora web | ingeniero informático/ingeniera informática
tecnologia: analista de datos | ingeniero de datos/ingeniera de datos
tecnologia: desarrollador de software/desarrolladora de software | ingeniero en sistemas/ingeniera en sistemas
comercio: comerciante | vendedor/vendedora | tendero/tendera | vendedor ambulante/vendedora ambulante
comercio: asesor comercial/asesora comercial | ejecutivo de ventas/ejecutiva de ventas
comercio: representante de ventas | mercaderista | impulsador/impulsadora | distribuidor/distribuidora
comercio: importador/importadora | empresario/empresaria | microempresario/microempresaria
comercio: emprendedor/emprendedora | negociante | comercializador/comercializadora
comercio: visitador médico/visitadora médica | agente inmobiliario/agente inmobiliaria
comercio: corredor inmobiliario/corredora inmobiliaria | vendedor de seguros/vendedora de seguros
comercio: cajero/cajera | dueño de negocio/dueña de negocio | tendero de barrio/tendera de barrio
transporte: conductor/conductora | conductor de plataforma/conductora de plataforma | taxista
transporte: camionero/camionera | piloto | piloto comercial | piloto de avión | mecánico/mecánica
transporte: mecánico automotriz/mecánica automotriz | domiciliario/domiciliaria | mensajero/mensajera
transporte: transportador/transportadora | auxiliar de vuelo | azafata | sobrecargo
transporte: controlador aéreo/controladora aérea | chofer | chofer de bus | conductor de bus/conductora de bus
transporte: despachador/despachadora | marinero/marinera | operador logístico/operadora logística
transporte: repartidor/repartidora | técnico automotriz/técnica automotriz | motorista
transporte: conductor de taxi/conductora de taxi | conductor de camión/conductora de camión
medios: periodista | comunicador social/comunicadora social | comunicador/comunicadora
medios: community manager | presentador/presentadora | locutor/locutora | publicista
medios: productor audiovisual/productora audiovisual | camarógrafo/camarógrafa | editor/editora
medios: reportero/reportera | redactor/redactora | creador de contenido/creadora de contenido
medios: influenciador/influenciadora | influencer | youtuber | relacionista público/relacionista pública
medios: productor de radio/productora de radio | presentador de televisión/presentadora de televisión
medios: social media manager | copywriter | editor de video/editora de video | comunicador audiovisual/comunicadora audiovisual
creativas: fotógrafo/fotógrafa | diseñador gráfico/diseñadora gráfica | diseñador de modas/diseñadora de modas
creativas: diseñador industrial/diseñadora industrial | diseñador/diseñadora | artista
creativas: artista plástico/artista plástica | pintor/pintora | músico/música | cantante
creativas: actor/actriz | bailarín/bailarina | escritor/escritora | ilustrador/ilustradora
creativas: animador/animadora | artesano/artesana | tatuador/tatuadora | dj | productor musical/productora musical
creativas: escultor/escultora | diseñador de interiores/diseñadora de interiores | modelo | ceramista
creativas: joyero/joyera | compositor/compositora | director de cine/directora de cine | guionista
creativas: curador/curadora | fotógrafo profesional/fotógrafa profesional | maquillador/maquilladora
servicios: administrador/administradora | administrador de empresas/administradora de empresas
servicios: estilista | peluquero/peluquera | barbero/barbera | manicurista | esteticista
servicios: cosmetólogo/cosmetóloga | secretario/secretaria | recepcionista
servicios: asistente administrativo/asistente administrativa | auxiliar administrativo/auxiliar administrativa
servicios: aseador/aseadora | empleado doméstico/empleada doméstica | empleada del servicio
servicios: niñero/niñera | cuidador/cuidadora | guía turístico/guía turística | agente de viajes
servicios: conserje | portero/portera | jardinero/jardinera | lavandero/lavandera | modista
servicios: costurero/costurera | sastre | zapatero/zapatera | cerrajero/cerrajera | masajista
servicios: administrador de propiedad horizontal/administradora de propiedad horizontal
servicios: trabajador social/trabajadora social | traductor/traductora | intérprete
servicios: operador de call center/operadora de call center | teleoperador/teleoperadora
servicios: mayordomo | asistente personal | auxiliar de servicios generales | lavador de carros/lavadora de carros
construccion: arquitecto/arquitecta | ingeniero civil/ingeniera civil | maestro de obra/maestra de obra
construccion: obrero/obrera | obrero de construcción/obrera de construcción | albañil | electricista
construccion: plomero/plomera | fontanero/fontanera | carpintero/carpintera | soldador/soldadora
construccion: topógrafo/topógrafa | contratista | constructor/constructora | interventor/interventora
construccion: inspector de obra/inspectora de obra | ingeniero eléctrico/ingeniera eléctrica
construccion: ebanista | pintor de obra/pintora de obra | residente de obra | técnico electricista/técnica electricista
gastronomia: chef | cocinero/cocinera | panadero/panadera | pastelero/pastelera | repostero/repostera
gastronomia: mesero/mesera | bartender | barista | carnicero/carnicera | auxiliar de cocina
gastronomia: administrador de restaurante/administradora de restaurante | sommelier | ayudante de cocina
agro: agricultor/agricultora | campesino/campesina | ganadero/ganadera | caficultor/caficultora
agro: cultivador/cultivadora | floricultor/floricultora | agrónomo/agrónoma
agro: ingeniero agrónomo/ingeniera agrónoma | pescador/pescadora | avicultor/avicultora
agro: porcicultor/porcicultora | jornalero/jornalera | zootecnista | apicultor/apicultora
agro: recolector de café/recolectora de café | administrador de finca/administradora de finca
agro: mayordomo de finca | productor agrícola/productora agrícola | cafetero/cafetera
seguridad: policía | patrullero/patrullera | militar | soldado | guarda de seguridad | vigilante
seguridad: escolta | bombero/bombera | detective | guardia de seguridad | investigador privado/investigadora privada
publico: funcionario público/funcionaria pública | servidor público/servidora pública
publico: empleado público/empleada pública | concejal/concejala | alcalde/alcaldesa
publico: diputado/diputada | funcionario/funcionaria | inspector de policía/inspectora de policía
industria: operario/operaria | operario de máquina/operaria de máquina | técnico industrial/técnica industrial
industria: ingeniero industrial/ingeniera industrial | ingeniero mecánico/ingeniera mecánica
industria: ingeniero químico/ingeniera química | ingeniero de petróleos/ingeniera de petróleos
industria: ingeniero ambiental/ingeniera ambiental | montacarguista | almacenista | bodeguero/bodeguera
industria: tornero/tornera | minero/minera | ingeniero de minas/ingeniera de minas | confeccionista
industria: técnico de mantenimiento/técnica de mantenimiento | operador de maquinaria/operadora de maquinaria
ingenieria: ingeniero/ingeniera
deporte: deportista | futbolista | ciclista | entrenador/entrenadora | preparador físico/preparadora física
deporte: árbitro/árbitra | instructor de gimnasio/instructora de gimnasio | atleta
deporte: entrenador personal/entrenadora personal | nadador/nadadora | tenista | patinador/patinadora
deporte: instructor de yoga/instructora de yoga | profesor de educación física/profesora de educación física
ciencia: biólogo/bióloga | químico/química | físico/física | matemático/matemática | geólogo/geóloga
ciencia: investigador/investigadora | científico/científica | estadístico/estadística
ciencia: astrónomo/astrónoma | microbiólogo/microbióloga | biotecnólogo/biotecnóloga
ciencia: antropólogo/antropóloga | sociólogo/socióloga | historiador/historiadora
ciencia: filósofo/filósofa | politólogo/politóloga | arqueólogo/arqueóloga
estudiante: estudiante | estudiante universitario/estudiante universitaria | universitario/universitaria
estudiante: estudiante de derecho | estudiante de medicina | estudiante de ingeniería | estudiante de enfermería
estudiante: estudiante de psicología | estudiante de administración | estudiante de contaduría
estudiante: estudiante de economía | estudiante de arquitectura | estudiante de diseño
estudiante: estudiante de comunicación social | estudiante de odontología | estudiante de veterinaria
estudiante: estudiante de sistemas | estudiante de ingeniería de sistemas | estudiante de ingeniería civil
estudiante: estudiante de ingeniería industrial | estudiante de licenciatura | estudiante de pregrado
estudiante: estudiante de posgrado | estudiante de maestría | estudiante de doctorado | estudiante de periodismo
estudiante: estudiante de publicidad | estudiante de fisioterapia | estudiante de nutrición | estudiante de música
hogar: ama de casa | amo de casa | dedicado al hogar/dedicada al hogar
pensionado: pensionado/pensionada | jubilado/jubilada | retirado/retirada
independiente: independiente | trabajador independiente/trabajadora independiente | freelance | freelancer
independiente: contratista independiente | desempleado/desempleada | trabajador informal/trabajadora informal
"""

# English terms (two documents of the corpus are in English).
OCCUPATIONS_EN_SPEC = """
creativas: photographer | graphic designer | designer | artist | musician | singer | writer | illustrator
medios: journalist | community manager | reporter | editor | content creator | influencer | publicist
derecho: lawyer | attorney | law student
finanzas: accountant | economist | financial analyst | auditor | banker
educacion: teacher | professor | tutor
salud: nurse | physician | dentist | psychologist | physiotherapist | physical therapist | veterinarian | pharmacist
transporte: driver | rideshare driver | pilot | commercial pilot | mechanic | taxi driver | truck driver
tecnologia: software engineer | systems engineer | developer | programmer | data scientist | software developer
construccion: architect | civil engineer | electrician | plumber | carpenter | construction worker
gastronomia: chef | cook | baker | waiter | waitress | bartender
comercio: merchant | shopkeeper | salesperson | entrepreneur | business owner | store owner
servicios: hairdresser | stylist | administrator | receptionist | secretary
agro: farmer | rancher
seguridad: police officer | firefighter | security guard
estudiante: student | medical student | university student
ingenieria: engineer
pensionado: retiree | pensioner
"""

# Terms that also have a non-occupation reading ("piloto" of a program, "física" as in
# physical card). OCCUPATION_TERMS still lists them; callers should require a cue such as
# "soy" / "trabajo como" before generalizing them (the engine's OCC_CUE already does).
AMBIGUOUS_TERMS = """
piloto cajero cajera modelo físico física químico química matemático matemática estadístico
estadística música militar policía independiente retirado retirada funcionario funcionaria
secretario secretaria conductor conductora editor editora diseñador diseñadora artista
universitario universitaria mayordomo sastre chofer soldado atleta ingeniero ingeniera
tutor tutora designer editor driver pilot cook student artist secretary engineer
"""

# Generic stems for occupations missing from the list (new rows after the corpus grows).
# Checked in order on the normalized occupation; first hit wins.
SECTOR_STEMS: list[tuple[str, str]] = [
    ("estudiant", "estudiante"), ("student", "estudiante"),
    ("ingeniero agron", "agro"), ("ingeniera agron", "agro"),
    ("ingenier", "ingenieria"), ("engineer", "ingenieria"),
    ("medic", "salud"), ("enfermer", "salud"), ("odont", "salud"), ("terapeut", "salud"),
    ("psicolog", "salud"), ("farmac", "salud"), ("veterinar", "salud"),
    ("cirujan", "salud"), ("clinic", "salud"), ("salud", "salud"), ("nurse", "salud"),
    ("docent", "educacion"), ("profesor", "educacion"), ("maestr", "educacion"),
    ("pedagog", "educacion"), ("educa", "educacion"), ("teacher", "educacion"),
    ("abogad", "derecho"), ("jurid", "derecho"), ("juez", "derecho"), ("notari", "derecho"),
    ("lawyer", "derecho"),
    ("contad", "finanzas"), ("contab", "finanzas"), ("financ", "finanzas"), ("banc", "finanzas"),
    ("econom", "finanzas"), ("tesor", "finanzas"), ("audit", "finanzas"), ("seguros", "finanzas"),
    ("sistemas", "tecnologia"), ("software", "tecnologia"), ("program", "tecnologia"),
    ("desarroll", "tecnologia"), ("informat", "tecnologia"), ("datos", "tecnologia"),
    ("tecnolog", "tecnologia"),
    ("conduct", "transporte"), ("chofer", "transporte"), ("pilot", "transporte"),
    ("mecanic", "transporte"), ("transport", "transporte"), ("taxi", "transporte"),
    ("camion", "transporte"), ("domicili", "transporte"), ("mensajer", "transporte"),
    ("periodis", "medios"), ("comunica", "medios"), ("locutor", "medios"), ("presentador", "medios"),
    ("publicis", "medios"), ("contenido", "medios"), ("redact", "medios"),
    ("fotograf", "creativas"), ("disen", "creativas"), ("artist", "creativas"), ("music", "creativas"),
    ("pintor", "creativas"), ("escritor", "creativas"), ("ilustra", "creativas"), ("artesan", "creativas"),
    ("arquitect", "construccion"), ("constru", "construccion"), ("obra", "construccion"),
    ("electric", "construccion"), ("plomer", "construccion"), ("carpinter", "construccion"),
    ("solda", "construccion"), ("albanil", "construccion"),
    ("cocin", "gastronomia"), ("chef", "gastronomia"), ("panad", "gastronomia"),
    ("paste", "gastronomia"), ("reposter", "gastronomia"), ("meser", "gastronomia"),
    ("restaur", "gastronomia"), ("gastronom", "gastronomia"),
    ("agricult", "agro"), ("campesin", "agro"), ("ganad", "agro"), ("cultiv", "agro"),
    ("pescad", "agro"), ("finca", "agro"), ("agro", "agro"), ("cafe", "agro"),
    ("vended", "comercio"), ("comerci", "comercio"), ("ventas", "comercio"), ("tender", "comercio"),
    ("negoci", "comercio"), ("empresari", "comercio"), ("emprend", "comercio"), ("tienda", "comercio"),
    ("polic", "seguridad"), ("vigilan", "seguridad"), ("segurid", "seguridad"), ("militar", "seguridad"),
    ("bomber", "seguridad"), ("escolta", "seguridad"),
    ("funcionari", "publico"), ("servidor publico", "publico"), ("servidora publica", "publico"),
    ("alcald", "publico"), ("concejal", "publico"),
    ("operari", "industria"), ("industri", "industria"), ("fabrica", "industria"), ("planta", "industria"),
    ("deport", "deporte"), ("entrenad", "deporte"), ("futbol", "deporte"), ("gimnas", "deporte"),
    ("investiga", "ciencia"), ("cientific", "ciencia"), ("biolog", "ciencia"), ("quimic", "ciencia"),
    ("pension", "pensionado"), ("jubilad", "pensionado"),
    ("hogar", "hogar"), ("ama de casa", "hogar"),
    ("costur", "servicios"), ("modist", "servicios"), ("sastr", "servicios"), ("confecc", "industria"),
    ("administra", "servicios"), ("estilist", "servicios"), ("peluquer", "servicios"),
    ("secretari", "servicios"), ("recepcion", "servicios"), ("asistente", "servicios"),
    ("auxiliar", "servicios"), ("servicio", "servicios"), ("belleza", "servicios"),
    ("independ", "independiente"), ("freelanc", "independiente"),
]

# Kipu staff roles: never treated as a customer's occupation in free text, because agents
# say "soy asesora", "soy analista de fraude" about their job at Kipu.
STAFF_ROLE_TERMS = """
asesor asesora agente analista coordinador coordinadora líder gerente director directora
supervisor supervisora ejecutivo ejecutiva auxiliar operador operadora practicante pasante
jefe jefa
"""
