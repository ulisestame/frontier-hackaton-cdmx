"""Hispanic / Colombian surnames.

SURNAMES is the recognition lexicon (also the generation candidates). Generation drops
the ones in SURNAME_NO_GENERATE: surnames that are common Spanish words (and would read
oddly or collide with fintech vocabulary such as "mora" or "plata"), places, brands, and
surnames tied to public figures. Anything that is also a given name or a barrio is dropped
programmatically in anon.lexicon.
"""


def _words(block: str) -> list[str]:
    return block.split()


SURNAMES = _words("""
Abad Abadía Abello Abondano Abril Acevedo Acero Achury Acosta Acuña Adarve Afanador Agámez
Agredo Aguado Agudelo Aguilar Aguilera Aguirre Alarcón Alba Albarracín Albornoz Alcalá
Alcázar Aldana Alean Alegría Alemán Aljure Almanza Almario Almeida Almonacid Alonso Altamar
Altamiranda Altamirano Alvarado Alvarán Álvarez Alvear Alzate Amado Amador Amariles Amaya
Ambuila Amézquita Amórtegui Anacona Anaya Andrade Angarita Ángel Angulo Antía Antolínez
Anzola Aparicio Aponte Apráez Aragón Arana Aranda Aranguren Aranzazu Araque Araújo Arbeláez
Arboleda Arce Arcila Arciniegas Arcos Ardila Arenas Arévalo Argáez Argote Argumedo Argüello
Arias Ariño Arismendi Aristizábal Ariza Arizmendi Arjona Armas Armenta Arrázola Arredondo
Arrieta Arroyave Arroyo Arrubla Arteaga Artunduaga Asencio Asprilla Atehortúa Atencia
Atuesta Ávila Avendaño Avilés Ayala Ayerbe Azcárate Azuero
Bacca Badillo Baena Báez Bahamón Balanta Balcázar Baldión Ballén Ballestas Ballesteros
Bañol Baquero Barahona Barajas Barbosa Barco Barón Barragán Barreneche Barrera Barreto
Barriga Barrientos Barrios Barros Bastidas Basto Bastos Batista Bautista Becerra Bedoya
Bejarano Belalcázar Beleño Bello Beltrán Benavides Benavídez Benítez Benjumea Bermeo
Bermúdez Bernal Berrío Berrocal Bertel Betancourt Betancur Bettín Blandón Blanco
Blanquicett Bobadilla Bocanegra Bohórquez Bolaños Bolívar Bonilla Borda Borja Bornacelli
Bornachera Borrero Bossa Botero Botía Bracamonte Bravo Briceño Bríñez Brito Buelvas Buendía
Bueno Buitrago Bula Burbano Burgos Bustamante Bustillo Bustos
Caballero Cabal Cabarcas Cabello Cabezas Cabra Cabrera Cáceres Cadavid Cadena Caicedo
Cajiao Calderón Calero Calle Callejas Calvo Camacho Camargo Camelo Campillo Campo Campos
Campuzano Cañas Cancino Canchila Candela Cano Cañón Cantillo Cantor Capera Capote Carabalí
Carbonell Carbonó Cárcamo Cárdenas Cardona Cardozo Carmona Caro Carranza Carrascal Carrasco
Carreño Carrero Carrillo Carulla Carvajal Casadiego Casalins Casallas Casanova Casas Casierra
Casseres Castañeda Castaño Castelblanco Castellanos Castellar Castiblanco Castilla Castillo
Castrillón Castro Cataño Causil Cavadía Ceballos Celis Cely Centeno Cepeda Cerón Cerpa
Cerquera Céspedes Chacón Chalarca Chamorro Chaparro Charry Chaverra Chaves Chávez Chica
Chinchilla Chiquillo Chitiva Cifuentes Cisneros Clavijo Cobo Cobos Cogollo Coley Collazos
Colmenares Colorado Conde Contreras Copete Coral Córdoba Corena Coronado Corrales Correa
Correal Cortázar Cortés Cortina Cotes Cotrino Covaleda Coy Crespo Cristancho Cruz Cuadrado
Cuadros Cuartas Cubides Cubillos Cudris Cuéllar Cuello Cuenca Cuervo Cuesta Cuevas Cujar
Curiel
Dager Dangond Dávila Daza Delgadillo Delgado Devia Diago Díaz Díez Dimaté Domínguez Donado
Dorado Duarte Dueñas Duque Durán Dussán
Echavarría Echeverri Echeverría Echeverry Elejalde Elles Enciso Enríquez Erazo Escalante
Escandón Escobar Escorcia Escudero Espejo Espinal Espinel Espinosa Espitia Esquivel Esquivia
Estévez Estrada Estupiñán
Fadul Fajardo Fals Fandiño Farfán Farías Feria Feris Fernández Ferrer Ferro Fierro
Figueredo Figueroa Flórez Florián Fonnegra Fonseca Fontalvo Forero Franco Fuenmayor Fuentes
Fuertes Fúquene
Gaitán Galán Galarcio Galarza Galeano Galindo Gallardo Gallego Gallo Galvis Gamboa Gámez
Gaona Garavito Garcés García Garizábalo Garnica Garrido Garzón Gaviria Gelves Gélvez Genes
Gerena Gil Giménez Giraldo Girón Godoy Goenaga Gómez Góngora González Gordillo Gracia
Grajales Granados Granda Grisales Gualdrón Guarín Guarnizo Guayara Guayazán Guerra Guerrero
Guete Guevara Güiza Guisao Gutiérrez Guzmán
Hazbún Henao Henríquez Herazo Heredia Hermida Hernández Herrán Herrera Hidalgo Higuera
Hincapié Hinestroza Hinojosa Holguín Hoyos Huérfano Huertas Hurtado
Ibáñez Ibargüen Ibarra Idárraga Iglesias Imbachí Infante Insignares Iregui Iriarte Isaza
Jácome Jaimes Jaramillo Jattin Jerez Jiménez Joya Junco Jurado
Lagos Lamprea Lancheros Landínez Lara Largo Lasso Lastra Latorre Laverde Leal Ledesma
Leguízamo Lemos Lemus Lenis León Lerma Leyva Lezama Libreros Linares Linero Lizarazo Lizcano
Llano Llanos Llinás Llorente Loaiza Lobatón Lobo Lombana Londoño Lopera López Lora Losada
Lotero Lozada Lozano Lucumí Lugo Luján Luna Luque
Macea Machado Macías Madrid Madrigal Maestre Mafla Mahecha Malagón Maldonado Mancera Mancilla
Manjarrés Manotas Manrique Mantilla Manzano Marín Mariño Marmolejo Márquez Marroquín Martelo
Martínez Marulanda Mattos Maya Mayorga Mazo Mazuera Medina Medrano Mejía Meléndez Melgarejo
Melo Mena Mendieta Méndez Mendivelso Mendoza Mercado Merchán Merlano Mesa Mestra Mestre Meza
Millán Mina Miranda Molano Molina Moncada Moncaleano Mondragón Monroy Monsalve Montaño
Montealegre Montenegro Montero Monterrosa Montes Montilla Montoya Mora Morales Morán Morantes
Morelo Moreno Morillo Moscoso Mosquera Motta Moya Moyano Mozo Múnera Muñetón Muñoz Murcia
Murgas Murillo Mutis
Nader Najar Nájera Naranjo Narváez Navarrete Navarro Navas Navia Negrete Neira Nieto Nieves
Niño Nisperuza Noguera Noreña Noriega Nossa Novoa Núñez
Obando Obregón Ocampo Ochoa Ojeda Olarte Olaya Olivares Olivella Olmos Oñate Oquendo Ordóñez
Orduz Orjuela Orozco Orrego Ortega Ortegón Ortiz Osorio Ospina Ospino Otálora Otálvaro Otero
Ovalle Oviedo
Pabón Pacheco Padilla Padrón Páez Palacio Palacios Palencia Pallares Palma Palmezano
Palomino Paniagua Pantoja Parada Páramo Pardo Paredes Pareja Parra Pastrana Patarroyo
Paternina Patiño Pava Paz Pedraza Pedroza Pedrozo Peláez Penagos Peña Peñaloza Peñuela Peralta
Perdomo Perea Pérez Pertuz Petro Pico Piedrahita Pimiento Pineda Pinilla Pinillos Pino Pinto
Pinzón Piñeres Piñeros Piraquive Pizarro Plata Polanco Polo Porras Portela Portilla Porto
Posada Poveda Prada Prado Prieto Puche Puello Puentes Puerta Pulido Pumarejo Pupo
Quesada Quevedo Quiceno Quijano Quintana Quintero Quiñones Quiñónez Quiroga Quiroz
Racero Ramírez Ramos Rangel Rebolledo Reina Rendón Rengifo Rentería Restrepo Revelo Rey
Reyes Riascos Riaño Rico Rincón Ríos Rivadeneira Rivas Rivera Rivero Riveros Roa Robayo
Robledo Robles Rocha Rodas Rodelo Rodríguez Rojano Rojas Roldán Romaña Romero Romo Roncancio
Rondón Ropero Rosado Rosales Rosas Rosero Rozo Rúa Ruano Rubio Rueda Ruiz
Saavedra Sabogal Sáenz Salamanca Salas Salazar Salcedo Saldaña Saldarriaga Salgado Salinas
Salom Samper Samudio Sanabria Sánchez Sanclemente Sandoval Sanmartín Santacruz Santamaría
Santana Santander Santofimio Santos Sanz Sarabia Sarmiento Segovia Segura Sepúlveda Serna
Serpa Serrano Sierra Silva Sinisterra Solano Sosa Sotelo Soto Sotomayor Suárez Suaza Suescún
Tabares Taborda Tafur Tamayo Tapia Tapias Tascón Teherán Tejada Tejeda Téllez Tello Tenorio
Tibaduiza Tinjacá Tique Tirado Tobón Toledo Tolosa Toncel Toro Torralba Torrente Torres
Torrijos Tovar Trejos Trespalacios Triana Trillos Trujillo Turizo
Ulloa Umaña Urbano Ureña Uribe Urquijo Urrea Urrego Urrutia Urueta Useche Usma Usuga
Vaca Valbuena Valdeblánquez Valderrama Valdés Valdivieso Valencia Valero Vallejo Valoyes
Vanegas Varela Vargas Varón Vásquez Vega Vela Velandia Velasco Velásquez Vélez Vence Ventura
Vera Verbel Vergara Vesga Vianchá Vidal Villa Villabona Villada Villadiego Villafañe Villalba
Villalobos Villamil Villamizar Villanueva Villaquirán Villarraga Villarreal Villegas Villota
Vivas Viveros
Yances Yanes Yáñez Yate Yepes Yusti
Zabala Zabaleta Zambrano Zamora Zamudio Zapata Zarama Zárate Zea Zuleta Zuluaga Zúñiga
""")

SURNAME_NO_GENERATE = set(_words("""
Mora Paz Plata Cuesta Caro Canal Mercado Barrios Calle Segura Puerta Cadena Cruz Fuentes
Campos Campo Casas Rico Bueno Blanco Luna Sierra Vega Villa Toro Ríos Montes Peña Prado Rosas
Salas Ramos Santos Reyes Rey Iglesias Leal Lobo Bravo Gallo Llano Llanos Lagos Palma Guerra
Guerrero Cabezas Paredes Feria Espejo Alegría Ventura Amado Conde Duque Franco Calvo Bello
Rubio Romero Robles Manzano Pinto Mesa Mina Nieves Cuervo Fierro Infante Pastor Gracia
Fuertes Colorado Cortina Mozo Pino Polo Junco Granda Coral Cabra Abril Alba Ángel Candela
Bolívar Santander Córdoba Toledo Madrid Cuenca Porto Lara
Petro Uribe Pastrana Gaviria Samper Escobar Gaitán Galán Botero Valderrama Asprilla Ibargüen
Mutis Carulla Uribe Vives Higuita Pajón Falcao
"""))
