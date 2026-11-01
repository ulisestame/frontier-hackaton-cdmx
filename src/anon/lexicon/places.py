"""Cities and barrios.

CORPUS_BARRIOS_BY_CITY holds the exact (city, barrio) pairs that appear in
tables/clientes.csv of the challenge corpus; those are the barrios that show up as
quasi-identifiers in free text. EXTRA_BARRIOS_BY_CITY adds well-known barrios of the main
Colombian cities so a replacement barrio does not always come from the same small list.
Barrio names built on a person's name (Simón Bolívar, Carlos E. Restrepo...) are left out.
"""

CORPUS_BARRIOS_BY_CITY: dict[str, list[str]] = {
    "Bogotá": ["Castilla", "Cedritos", "Chapinero", "Chicó", "Galán", "Kennedy", "La Candelaria",
               "Restrepo", "Santa Fe", "Suba", "Teusaquillo"],
    "Medellín": ["Belén", "Boston", "Buenos Aires", "Castilla", "El Poblado", "Envigado", "Itagüí",
                 "La América", "Laureles", "Manrique", "Robledo", "Sabaneta"],
    "Cali": ["Ciudad Jardín", "El Peñón", "Granada", "San Fernando", "Santa Mónica"],
    "Barranquilla": ["Boston", "El Prado", "Riomar", "Villa Country"],
    "Bucaramanga": ["Cabecera", "Cañaveral", "Lagos del Cacique", "Real de Minas", "Sotomayor"],
    "Cartagena": ["Bocagrande", "Castillogrande", "Crespo", "Getsemaní", "Manga", "Pie de la Popa"],
    "Pereira": ["Circunvalar", "Cuba", "Dosquebradas", "Pinares", "Villa Olímpica", "Álamos"],
}

EXTRA_BARRIOS_BY_CITY: dict[str, list[str]] = {
    "Bogotá": ["Usaquén", "Rosales", "El Retiro", "La Soledad", "Palermo", "Galerías", "Modelia",
               "Ciudad Salitre", "Normandía", "Marly", "Niza", "Colina Campestre", "Mazurén", "Bosa",
               "Fontibón", "Engativá", "Tunjuelito", "Las Ferias", "Patio Bonito", "Timiza",
               "Hayuelos", "La Macarena", "Quinta Camacho", "Pasadena", "La Castellana", "El Batán",
               "La Alhambra", "Puente Aranda", "Bachué", "La Esmeralda", "Gran América",
               "Siete de Agosto", "Toberín", "Verbenal", "Britalia", "Mandalay", "El Tintal",
               "Chapinero Alto", "Bella Suiza", "Lisboa"],
    "Medellín": ["Estadio", "Conquistadores", "Florida Nueva", "Calasanz", "Los Colores",
                 "Prado Centro", "Aranjuez", "Villa Hermosa", "San Javier", "Guayabal", "Provenza",
                 "Manila", "Suramericana", "Naranjal", "La Floresta", "Altavista", "Doce de Octubre",
                 "Popular", "Las Acacias", "Los Balsos", "El Diamante", "La Mota", "Santa Lucía",
                 "Los Almendros", "Las Palmas", "El Salvador", "Cristo Rey",
                 "La Candelaria", "Loreto"],
    "Cali": ["San Antonio", "El Ingenio", "Pance", "Tequendama", "Versalles", "Normandía",
             "Juanambú", "El Refugio", "Capri", "Siloé", "Alameda", "Champagnat", "Cristales",
             "El Lido", "Prados del Norte", "La Flora", "Valle del Lili", "Mayapán", "El Caney",
             "Primero de Mayo", "Bretaña", "Junín", "El Vallado", "Los Álamos", "La Hacienda",
             "Ciudad Córdoba", "Santa Isabel", "El Limonar"],
    "Barranquilla": ["Alto Prado", "Altos del Prado", "El Golf", "Ciudad Jardín", "Las Delicias",
                     "Paraíso", "Bellavista", "Miramar", "Los Alpes", "El Tabor", "Los Nogales",
                     "La Concepción", "Rebolo", "Barrio Abajo", "El Recreo", "Montecristo",
                     "Granadillo", "Andalucía", "Betania", "La Victoria", "El Silencio",
                     "Villa Campestre", "Las Estrellas", "Los Andes"],
    "Bucaramanga": ["San Alonso", "La Concordia", "Provenza", "Mejoras Públicas", "El Prado",
                    "San Francisco", "La Victoria", "Terrazas", "Conucos", "Los Pinos",
                    "Diamante II", "Campo Hermoso", "El Jardín", "Ciudadela Real de Minas",
                    "La Aurora", "Pan de Azúcar", "Cabecera del Llano", "Lagos II",
                    "El Bosque"],
    "Cartagena": ["El Laguito", "Marbella", "El Cabrero", "San Diego", "La Matuna", "Pie del Cerro",
                  "Torices", "El Bosque", "Los Alpes", "Chambacú", "Los Ejecutivos", "El Recreo",
                  "Ternera", "Alto Bosque", "Zaragocilla", "Canapote", "La Boquilla",
                  "Serena del Mar", "Crespito", "Bocagrande Norte", "Amberes", "Los Caracoles"],
    "Pereira": ["Maraya", "Belmonte", "El Jardín", "Boston", "Corales", "Los Alpes", "El Poblado",
                "Laureles", "Centro", "Cerritos", "Samaria", "El Dorado", "Providencia",
                "Pinares de San Martín", "Galicia", "Kennedy", "Villa Santana", "La Badea",
                "Nacederos", "San Joaquín"],
    "Manizales": ["Chipre", "Palermo", "Milán", "La Enea", "Palogrande", "Los Rosales", "La Sultana",
                  "El Cable", "Versalles", "La Castellana", "Bosques del Norte", "El Bosque",
                  "Alta Suiza", "Baja Suiza", "Campohermoso", "La Francia", "San Jorge", "Belén",
                  "Laureles"],
    "Cúcuta": ["Caobos", "La Riviera", "Quinta Oriental", "Prados del Este", "La Ceiba", "Colsag",
               "La Playa", "Barrio Blanco", "El Contento", "Latino", "Motilones", "Guaimaral",
               "Niza", "San Luis", "Atalaya", "La Libertad", "Popular", "Los Acacios", "Sevilla",
               "Torcoroma", "Chapinero", "El Rosal"],
    "Santa Marta": ["El Rodadero", "Bello Horizonte", "Pozos Colorados", "Taganga", "Gaira",
                    "Mamatoco", "El Prado", "Los Almendros", "Centro Histórico", "Pescaíto",
                    "Manzanares", "Jardín", "Los Alcázares", "Curinca", "Santa Fe", "Bavaria",
                    "Villa Concha", "Los Trupillos", "El Pando"],
    "Ibagué": ["Cádiz", "La Pola", "Belén", "Piedra Pintada", "El Salado", "Jordán", "Picaleña",
               "Ambalá", "Interlaken", "Calambeo", "Santa Helena", "La Francia", "El Vergel",
               "Varsovia", "Los Mandarinos", "Combeima", "Arkacentro", "Las Américas", "Boquerón",
               "La Gaviota"],
    "Villavicencio": ["El Barzal", "La Esperanza", "Buque", "Barzal Alto", "Siete de Agosto",
                      "El Caudal", "La Grama", "Brisas del Guatiquía", "El Estero",
                      "Porfía", "Montecarlo", "Covisán", "Rosablanca"],
    "Pasto": ["Las Cuadras", "Palermo", "Pandiaco", "La Aurora", "Chapultepec", "Las Acacias",
              "San Ignacio", "Morasurco", "Torobajo", "El Dorado", "Santa Mónica", "Mijitayo"],
    "Montería": ["La Castellana", "El Recreo", "Los Laureles", "Buenavista", "La Granja", "Centro",
                 "Pasatiempo", "El Dorado", "Montería Moderno", "La Floresta", "Mocarí", "Sucre"],
    "Neiva": ["Altico", "Quebraditas", "Las Granjas", "El Jardín", "Ipanema",
              "Santa Inés", "Los Mártires", "Las Palmas", "Buganviles", "Canaima"],
    "Armenia": ["La Castellana", "Laureles", "Los Profesionales", "La Patria", "El Bosque",
                "Granada", "Bosques de Pinares",
                "El Paraíso"],
    "Popayán": ["Centro Histórico", "Bello Horizonte", "La Esmeralda", "El Modelo", "Pandiguando",
                "Yanaconas", "La Ladera", "Pomona", "El Recuerdo", "Lomas de Granada", "Moscopán",
                "La Paz"],
    "Tunja": ["Centro", "Los Muiscas", "Las Quintas", "La Fuente", "Santa Inés",
              "Mesopotamia", "San Antonio", "Hunzahúa", "Altamira", "Los Cristales", "Suamox"],
    "Valledupar": ["Novalito", "Los Mayales", "Sicarare", "Garupal", "El Prado",
                   "Los Cortijos", "Primero de Mayo", "Mareigua", "La Nevada", "Cañahuate"],
}

# Barrio names present in almost every Colombian city, for cities without a list.
GENERIC_BARRIOS: list[str] = [
    "Centro", "La Esperanza", "Los Alpes", "El Recreo", "La Floresta", "Las Américas", "El Bosque",
    "Los Pinos", "La Libertad", "El Jardín", "Primero de Mayo", "Las Palmas", "Villa Nueva",
    "La Pradera", "Los Rosales", "El Porvenir", "Las Brisas", "Bellavista", "El Prado",
    "Los Almendros", "La Esmeralda", "El Paraíso", "Las Acacias", "Los Naranjos",
]

# canonical city -> aliases (normalized form is computed in anon.lexicon)
CITY_ALIASES: dict[str, list[str]] = {
    "Bogotá": ["Bogota", "Bogotá D.C.", "Bogota D.C.", "Bogotá DC", "Bogota DC", "Santa Fe de Bogotá",
               "Santafé de Bogotá", "Bogotá, D.C."],
    "Medellín": ["Medellin"],
    "Cali": ["Santiago de Cali"],
    "Barranquilla": [],
    "Bucaramanga": [],
    "Cartagena": ["Cartagena de Indias"],
    "Pereira": [],
    "Manizales": [],
    "Cúcuta": ["Cucuta", "San José de Cúcuta", "San Jose de Cucuta"],
    "Santa Marta": [],
    "Ibagué": ["Ibague"],
    "Villavicencio": [],
    "Pasto": ["San Juan de Pasto"],
    "Montería": ["Monteria"],
    "Neiva": [],
    "Armenia": [],
    "Popayán": ["Popayan"],
    "Tunja": [],
    "Valledupar": [],
}

# Departments and other places, for NON_NAME_WORDS and checks; not barrios.
DEPARTMENTS: list[str] = [
    "Amazonas", "Antioquia", "Arauca", "Atlántico", "Bolívar", "Boyacá", "Caldas", "Caquetá",
    "Casanare", "Cauca", "Cesar", "Chocó", "Córdoba", "Cundinamarca", "Guainía", "Guaviare",
    "Huila", "La Guajira", "Magdalena", "Meta", "Nariño", "Norte de Santander", "Putumayo",
    "Quindío", "Risaralda", "San Andrés", "Santander", "Sucre", "Tolima", "Valle del Cauca",
    "Vaupés", "Vichada",
]

OTHER_MUNICIPALITIES: list[str] = [
    "Envigado", "Itagüí", "Sabaneta", "Bello", "Rionegro", "La Ceja", "Chía", "Soacha",
    "Zipaquirá", "Facatativá", "Girardot", "Fusagasugá", "Mosquera", "Funza", "Cajicá", "Palmira",
    "Buenaventura", "Tuluá", "Buga", "Cartago", "Jamundí", "Yumbo", "Soledad", "Malambo",
    "Floridablanca", "Girón", "Piedecuesta", "Barrancabermeja", "Dosquebradas", "Santa Rosa de Cabal",
    "Turbaco", "Sincelejo", "Riohacha", "Quibdó", "Yopal", "Florencia", "Mocoa", "Leticia",
    "San Gil", "Duitama", "Sogamoso", "Apartadó", "Turbo", "Caucasia", "Magangué", "Ocaña",
    "Pamplona", "Tumaco", "Ipiales", "Maicao", "Aguachica", "Honda", "Melgar", "Guatapé",
    "Santa Fe de Antioquia", "Villa de Leyva", "Barichara", "Salento", "Filandia",
]
