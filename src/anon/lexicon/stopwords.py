"""Capitalized words that are not part of a person's name.

Used to stop a name sequence in free text ("Laura Bancolombia" is not a person). Given
names and surnames from the lexicons are subtracted when the final set is built, so a
word that can be a surname (Santander, Bolívar, Córdoba...) never stops a name. Months
and weekdays are kept even when they are also names (Julio, Domingo).
"""


def _words(block: str) -> list[str]:
    return block.split()


FUNCTION_WORDS = _words("""
de del la las los el lo le les y e o u a al en con por para sin sobre entre hasta desde hacia
que qué como cómo cuando cuándo donde dónde quien quién quienes cual cuál cuales cuáles cuanto
este esta estos estas ese esa esos esas eso esto aquel aquella mi mis tu tus su sus nuestro
nuestra nuestros nuestras vuestro se me te nos ya no si sí muy más menos también tampoco pero
porque pues entonces aunque mientras luego así aquí ahí allí allá acá hoy ayer mañana ahora
antes después siempre nunca todo toda todos todas cada otro otra otros otras mismo misma
yo tú vos usted ustedes él ella ellos ellas nosotros nosotras eh ah oh uy ay jaja jajaja
un una unos unas uno dos tres cuatro cinco seis siete ocho nueve diez cien mil primer primero
primera segunda tercero tercera último última
""")

DISCOURSE_WORDS = _words("""
hola holi buenos buenas buen día días dias tardes noches saludos saludo atentamente
cordialmente gracias muchas mil listo lista perfecto perfecta claro bueno buena vale ok okay
oki dale hágale hagale chao adiós adios bien mal excelente genial súper super entendido
entendida correcto correcta exacto exacta disculpa disculpe perdón perdon permiso favor
porfa porfavor feliz felices bienvenido bienvenida bienvenidos atención asunto re fwd rv
importante urgente nota notas ps pd ojo hey hi hello dear thanks thank you best regards
sincerely cheers please yes yeah sure great welcome good morning afternoon evening
""")

TITLE_ROLE_WORDS = _words("""
señor señora señorita sr sra srta sres don doña dr dra doctor doctora ing ingeniero ingeniera
lic licenciado licenciada prof profesor profesora mr mrs ms miss sir madam cliente clienta
clientes agente agentes asesor asesora asesores analista analistas coordinador coordinadora
líder lider gerente gerentes director directora jefe jefa supervisor supervisora ceo cto cfo
coo cmo vp equipo soporte área area gerencia dirección direccion comité comite junta
presidente presidenta vicepresidente secretario secretaria tesorero titular titulares usuario
usuaria usuarios bot asistente virtual mamá mama papá papa hijo hija esposo esposa hermano
hermana tío tía primo prima abuelo abuela familiar compañero compañera colega
""")

BUSINESS_WORDS = _words("""
banco bancos cuenta cuentas tarjeta tarjetas crédito credito créditos débito debito pago pagos
cobro cobros cuota cuotas saldo saldos extracto extractos factura facturas transferencia
consignación consignacion abono reverso reversión reversiones contracargo préstamo prestamo
plazo interés intereses seguro seguros póliza poliza app aplicación aplicacion plataforma
llave clave contraseña código codigo perfil correo celular teléfono telefono número numero
documento documentos cédula cedula pasaporte radicado caso casos ticket pqr pqrs queja quejas
reclamo reclamos petición peticion solicitud respuesta incidente incidentes fraude riesgo
riesgos calidad producto productos ingeniería ingenieria marketing legal jurídico juridico
operaciones tecnología tecnologia seguridad talento humano nómina nomina informe informes
reporte reportes acta actas minuta minutas memo manual política politica plan planes
comunicado evaluación evaluacion desempeño auditoría auditoria organigrama carta contrato
acuerdo anexo resumen adjunto archivo archivos cobranza cobranzas mora vencimiento vencida
vencido onboarding escalamiento escalamientos general canal canales hilo mensaje mensajes
datos dato habeas data compra compras venta ventas comercio comercios establecimiento
monto montos valor pesos cop usd dólares dolares retiro retiros depósito deposito
trimestre semestre año mes semana fecha hora cierre corte reporte q1 q2 q3 q4 kpi sla
inc llc ltd corp sas s.a.s sa ltda company team report summary meeting notes agenda update
security risk customer customers client support account card credit payment payments loan
fraud quarterly board investor investors vendor agreement policy review
""")

BRANDS_ORGS = _words("""
kipu pay kipupay kipi bancolombia davivienda bbva nequi daviplata pse efecty baloto movii
lulo nu nubank rappi rappipay carulla éxito exito olímpica olimpica falabella alkosto jumbo
homecenter ara d1 nutresa unicentro andino avianca claro movistar tigo wom whatsapp google
apple android iphone visa mastercard amex superfinanciera superintendencia sic dian
datacrédito datacredito transunion cifin registraduría registraduria policía policia
fiscalía fiscalia procuraduría procuraduria contraloría contraloria slack gmail hotmail
outlook yahoo icloud zoom teams excel word pdf colpatria scotiabank itaú itau occidente
agrario caja social colsubsidio cafam compensar comfama comfenalco sura bancoomeva coomeva
veloz uber didi cabify picap mercadolibre amazon netflix spotify
""")

PLACES = _words("""
colombia bogotá bogota medellín medellin cali barranquilla cartagena bucaramanga manizales
cúcuta cucuta ibagué ibague villavicencio pasto montería monteria neiva popayán popayan tunja
valledupar sincelejo riohacha quibdó quibdo envigado itagüí itagui sabaneta rionegro chía chia
soacha zipaquirá zipaquira palmira buenaventura tuluá tulua floridablanca piedecuesta
barrancabermeja dosquebradas yopal leticia mocoa antioquia cundinamarca valle atlántico
atlantico risaralda tolima huila meta boyacá boyaca cauca quindío quindio chocó choco putumayo
caquetá caqueta casanare arauca guajira amazonas vichada guaviare vaupés guainía méxico mexico
españa espana miami panamá panama ecuador perú peru venezuela chile argentina brasil usa eeuu
estados unidos europa madrid
calle carrera avenida diagonal transversal barrio apto apartamento torre casa oficina local
piso sur norte este oeste centro plaza parque comercial edificio conjunto urbanización vereda
km kilómetro vía via
""")

MONTHS_DAYS = _words("""
enero febrero marzo abril mayo junio julio agosto septiembre setiembre octubre noviembre
diciembre lunes martes miércoles miercoles jueves viernes sábado sabado domingo
january february march april may june july august september october november december
monday tuesday wednesday thursday friday saturday sunday
""")
