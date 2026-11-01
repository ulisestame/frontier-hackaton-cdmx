"""Colombian given names labeled by gender, plus the subsets used to generate pseudonyms.

Pools (used to *generate* pseudonyms) only hold names whose gender is unambiguous both
by lexicon and by the usual Spanish suffix heuristic: female pool names end in "a",
male pool names never do. Names that are common words, places or ambiguous across
countries live only in the *lexicon* (used to *recognize* and gender real names).
"""


def _words(block: str) -> list[str]:
    return block.split()


# --- female, generation pools -------------------------------------------------------

F_COMMON = _words("""
Adela Adelaida Adriana Agustina Aída Alba Aleida Alejandra Alexandra Alicia Alina Amalia
Amanda Amelia Ana Analía Ángela Angélica Angelina Anita Antonella Antonia Ariadna Ariana
Aura Aurora Bárbara Berta Bianca Bibiana Brenda Camila Candelaria Carla Carlota Carmela
Carmenza Carolina Catalina Cecilia Celia Celina Cinthia Clara Clarisa Claudia Constanza
Cristina Dalia Daniela Danna Dayana Débora Delia Deyanira Diana Dora Edilma Elena Eliana
Elisa Elsa Elvia Elvira Emilia Emma Erika Esmeralda Estefanía Estela Eugenia Eva Fabiana
Fabiola Fernanda Flavia Florencia Francisca Gabriela Georgina Gilma Gina Giovanna Gisela
Graciela Helena Hilda Ileana Irma Isabela Isabella Ivana Jacinta Jessica Jimena Johana
Johanna Josefa Josefina Juana Juanita Julia Juliana Julieta Karina Karla Katia Laura
Leticia Lida Lidia Ligia Lilia Liliana Lina Lorena Lucía Luciana Lucila Lucrecia Luisa
Magdalena Magnolia Maira Manuela Mara Marcela Margarita María Mariana Maricela Mariela
Marina Maritza Marta Martha Martina Matilda Maura Mayra Melisa Micaela Milena Mireya
Mónica Nadia Natalia Nathalia Nidia Noelia Nora Norma Nubia Ofelia Olga Olivia Omaira
Pamela Paola Patricia Paula Paulina Priscila Rafaela Ramona Rebeca Regina Renata Rita
Roberta Romina Rosalba Rosalía Rosana Roxana Rubiela Sabrina Samanta Sandra Sara Silvana
Silvia Sofía Sonia Stella Susana Tamara Tania Tatiana Teresa Valentina Valeria Vanessa
Verónica Victoria Vilma Virginia Viviana Ximena Xiomara Yadira Yesenia Yolanda Yolima
Yuliana Zoila Zoraida Zulma
""")

F_EXTENDED = _words("""
Adalgisa Adelia Adelina Agripina Aitana Alana Albertina Albina Alcira Alejandrina Alessandra
Alexia Alfonsina Alisa Almudena Alondra Amaia Amaranta Amira Aminta Anabella Anastasia
Antonela Apolonia Aranza Arcelia Argelia Ariela Arianna Armida Asunta Atenea Aurelia Avelina
Ayda Begoña Belarmina Benedicta Benilda Benita Bernarda Bertha Brígida Briana Brisa Candela
Carina Carmina Casandra Casilda Caterina Cayetana Celestina Celmira Celsa Cira Clarita
Claudina Clementina Cristiana Custodia Daira Dalila Damiana Daniella Delfina Demetria Dilia
Dina Dionisia Dioselina Domitila Donata Dorinda Dorotea Dulcinea Edelia Edelmira Edna
Elba Eleana Eleonora Elida Elodia Eloísa Emelina Emérita Emiliana Eneida Engracia Enriqueta
Ercilia Erica Ermelinda Erminia Ernestina Etelvina Eudora Eufemia Eulalia Eusebia
Evangelina Evelia Fabricia Fausta Faustina Federica Felicia Felipa Felisa Fermina Fidelia
Fidelina Filomena Fiorella Floralba Florentina Florinda Francesca Gala Galilea Gema Gemma
Genara Genoveva Geraldina Gianna Gilda Giuliana Graciana Gregoria Greta Griselda Guillermina
Hanna Helga Herlinda Hermelinda Hermilda Herminia Hilaria Hipólita Honoria Idalia Ifigenia
Ilda Iliana Imelda Indira Inocencia Irina Isadora Isaura Isidora Ivanna Jana Jazmina
Joaquina Jordana Jovita Justina Kiara Laila Lara Laureana Leandra Leila Lena Leocadia
Leonarda Leonela Leonora Leopoldina Lía Liana Lisa Livia Loida Lola Lorenza Luana Lucelia
Lucinda Ludivia Ludmila Lupita Luzmila Macarena Mafalda Maia Malena Manuelita Marcelina
Marcia Mariángela Marianela Marisa Marisela Marla Maximina Maya Melania Melba Melida Melina
Minerva Mirella Mirna Mirta Natasha Narcisa Nélida Nemesia Nerea Nicolasa Ninfa Nohora
Noralba Norberta Nuria Obdulia Octavia Odilia Olimpia Olinda Oriana Orfilia Otilia Pascuala
Petra Petrona Pía Raimunda Ricarda Rigoberta Rosalinda Rosaura Rosenda Rosina Rosmira
Rufina Sabina Samantha Sarita Saturnina Sebastiana Selena Senaida Serafina Severina Sheila
Silveria Silvina Simona Sixta Soraya Stefanía Tecla Telma Teodora Teófila Teresita Thalía
Tomasa Tulia Umbelina Úrsula Valeska Vanesa Venancia Vicenta Wanda Wilma Yamila Yanira
Yaritza Yasmina Yésica Yohana Zaida Zenaida Zulema Zuleima
Ada Adalberta Adalia Adelma Adolfina Águeda Aixa Albana Alberta Alesia Alexa Alfonsa Alida
Almira Amabilia Amancia Amelina Andreína Angelita Araminta Arcadia Armanda Artemisa Atilia
Áurea Balbina Baltasara Basilia Belinda Bernardita Blandina Bonifacia Brunilda Calixta Cándida
Carmiña Carola Catarina Celedonia Cesárea Cipriana Clodomira Colomba Concepta Consolata Corina
Cornelia Crescencia Crisanta Dámasa Dania Darla Davinia Delma Domenica Dominga Dominica Doralba
Dorila Edilia Edita Edwina Elcira Elicia Elvinia Enelia Enilda Erlinda Estefana Eudocia Eufrasia
Evelina Ezequiela Facunda Fidela Filipa Flaminia Floriana Fulvia Gaudencia Gerarda Germana
Gilberta Gimena Glenda Gumersinda Heliodora Henriqueta Hermencia Hermila Higinia Honorata
Isolina Itala Jacoba Janna Jesusa Jorgelina Julisa Lavinia Leonilda Letizia Leyla Liduvina
Lisandra Lizandra Loreta Lorna Ludovica Luisina Macrina Maclovia Malvina Manolita Marciana
Marianita Marilda Marilena Marilia Marlena Martiniana Matea Maximiliana Melchora Moira Natalina
Nayara Nazaria Nicanora Nilda Nilsa Olegaria Onelia Orfelina Paulita Petronila Porfiria Prisca
Quiteria Ramira Reinalda Restituta Ricardina Rogelia Romelia Rosalva Rosela Rossana Sandrina
Selmira Severiana Silvestra Sinforosa Tadea Teodolinda Teodosia Tiburcia Tomasina Ubaldina
Valeriana Verena Veneranda Vicentina Vidalina Virgelina Yaneira Yanina Zenobia Zobeida Alessia
Arantxa Briseida Gianella Mikaela Nahia Zaira Herminda Dayanna Melissa Yuliza Leidiana Marbelia
""")

# --- male, generation pools ----------------------------------------------------------

M_COMMON = _words("""
Aarón Abel Abelardo Abraham Adolfo Adrián Agustín Alberto Albeiro Alcides Aldemar Alejandro
Alexander Alfonso Alfredo Alirio Alonso Álvaro Amaury Anderson Andrés Aníbal Antonio
Arcesio Argemiro Armando Arnulfo Arturo Augusto Aurelio Baltasar Benjamín Bernardo Braulio
Bruno Camilo Carlos César Ciro Claudio Cristian Cristóbal Damián Daniel Darío David Diego
Dionisio Edgar Edilberto Edison Eduardo Edwin Efraín Elías Eliécer Eliseo Elkin Emiliano
Emilio Enrique Ernesto Esteban Eugenio Ezequiel Fabián Fabio Federico Felipe Félix Fernando
Ferney Fidel Francisco Franco Gabriel Gerardo Germán Gilberto Gonzalo Gregorio Guillermo
Gustavo Harold Héctor Heriberto Hernán Hernando Horacio Hugo Humberto Ignacio Isaac Ismael
Iván Jacinto Jacobo Jaime Jairo Javier Jeremías Jerónimo Joaquín Joel Jonathan Jorge José
Josué Juan Julián Julio Leandro Leonardo Leonel Leopoldo Libardo Lisandro Lorenzo Lucas
Luciano Lucio Luis Manuel Marcelo Marco Marcos Mariano Mario Martín Mateo Matías Mauricio
Mauro Maximiliano Miguel Milton Misael Moisés Nelson Néstor Nicanor Nicolás Norberto Octavio
Omar Orlando Óscar Osvaldo Oswaldo Pablo Pascual Patricio Pedro Rafael Ramiro Ramón Raúl
Reinaldo Renato Ricardo Rigoberto Roberto Robinson Rodolfo Rodrigo Rogelio Rolando Román
Rubén Samuel Santiago Saúl Sebastián Sergio Silvio Simón Teodoro Tiberio Tobías Tomás
Uriel Valentín Vicente Víctor Wilson Wilmer Yesid
""")

M_EXTENDED = _words("""
Abdón Abdiel Abner Adalberto Adán Adelmo Agapito Alan Alcibíades Aldo Alipio Amadeo Ambrosio
Amílcar Amós Anacleto Anastasio Anselmo Antero Aparicio Apolinar Apolonio Aquiles Aquilino
Arcadio Arístides Aristóbulo Arley Arnoldo Arsenio Atilio Aureliano Avelino Axel Baldomero
Bartolomé Basilio Baudilio Bayron Benedicto Benicio Benito Bernabé Bernardino Blas Bonifacio
Boris Brandon Breiner Calixto Cándido Carmelo Casimiro Cayetano Ceferino Celedonio Celso
Cesáreo Cipriano Cirilo Clemente Cleto Clímaco Clodomiro Conrado Constantino Cornelio Cosme
Crisanto Crispín Cristino Dante Darwin Delfín Delio Demetrio Desiderio Didier Diógenes Donato
Doroteo Duván Edelberto Edelmiro Edier Edilson Edinson Edmundo Edwar Efrén Eider Eladio
Elmer Eloy Emerson Emeterio Emiro Emmanuel Enoc Epifanio Erasmo Eriberto Erick Erwin Esaú
Eudoro Eulogio Eusebio Eustaquio Evaristo Evelio Fabricio Facundo Faustino Fausto Fermín
Fernán Filiberto Flavio Florencio Florentino Florián Franklin Freddy Froilán Fulgencio
Gabino Gael Gamaliel Gaspar Gastón Genaro Gerson Gervasio Gildardo Giovanni Godofredo
Gualberto Guido Gumersindo Helmer Heliodoro Henry Hermes Herminio Higinio Hilario Hipólito
Holman Homero Honorio Ildefonso Isaías Isidoro Isidro Ítalo Jader Jefferson Jhon Johan
Jonás Jovanny Justiniano Juvenal Ladislao Lamberto Laureano Lázaro Leocadio Leónidas Lino
Lizardo Lucindo Ludovico Macario Maicol Manolo Marcelino Marcial Marino Marlon Martiniano
Maximino Medardo Melchor Milciades Nahún Narciso Natanael Nazario Nemesio Nepomuceno
Nicodemo Nilson Noé Norbey Octaviano Olegario Onofre Ovidio Pantaleón Paulino Pío Plinio
Plutarco Policarpo Porfirio Quintín Radamés Raimundo Reinel Remigio Reynaldo Rómulo
Rosendo Rubiel Rufino Sabino Salomón Sandro Saturnino Senén Serafín Severiano Silvano
Silvestre Simeón Sixto Sócrates Stiven Teobaldo Teodomiro Teodosio Teófilo Thiago Tito
Toribio Ubaldo Urbano Valdemar Valerio Venancio Vidal Virgilio Vladimir Wálter Wenceslao
Wilberto Wilfredo Wilmar Yair Yamid Yeison Yerson Zacarías Zenón Zoilo
Abdías Abelino Abundio Acacio Adalid Adelino Agenor Albino Aldair Alfio Aliro Amancio Amaro
Anatolio Aniceto Antonino Aquileo Argiro Aristarco Armandino Arquímedes Artemio Asdrúbal
Atanasio Benancio Benildo Bertoldo Cancio Candelario Casiano Cástulo Cecilio Celín Cenón
Clotario Dalmiro Dámaso Danilo Diomedes Domiciano Donaldo Edelio Edgardo Egidio Eleazar
Eleuterio Elidio Elio Eliut Emérito Emigdio Emilson Enrico Ermes Estanislao Eulises Evangelino
Everardo Exequiel Eyder Feliciano Fidencio Filemón Flaminio Floriberto Floro Galo Gaudencio
Geovanny Gilmer Hamilton Haroldo Heber Helio Heraclio Herculano Hilarión Hildebrando Honorato
Iginio Jacob Jasón Jenaro Jerson Josías Justino Laurentino Lauro Leovigildo Licinio Lisardo
Lisímaco Livio Lucrecio Macedonio Magdaleno Malaquías Manfredo Marciano Melquíades Nataniel
Nicéforo Nicomedes Odilio Olimpo Orestes Otoniel Pancracio Paulo Pelayo Pompilio Procopio
Publio Régulo Remberto Romualdo Roque Rosalino Ruperto Salustiano Sancho Secundino Severino
Sigifredo Sinforiano Tancredo Telésforo Timoteo Tirso Ulpiano Victoriano Walberto Zósimo Alejo
Amir Ángelo Bastián Dairo Duberney Eduar Emanuel Erney Giovanny Jhonier Santino Valentino
Yonatan Albán Alcides Anderson Benigno Ezequiel Gonzalo Heliberto Hernany Jaider Jairo
""")

# --- lexicon-only names (recognized and gendered, never generated) -------------------

F_OTHER = _words("""
Abigail Abigaíl Abril Alma Amada Amparo Anabel Ángeles Araceli Aracely Astrid Azucena
Beatriz Belén Bella Berenice Betty Blanca Camelia Caridad Carmen Catherine Celeste Cielo
Clemencia Concepción Consuelo Daisy Deisy Derly Dolores Doris Dulce Edith Elizabeth Elsy
Esperanza Ester Esther Estrella Evelyn Fanny Fátima Flor Francia Gladis Gladys Gloria
Guadalupe Heidi Hortensia Inés Ingrid Iris Irene Isabel Ivonne Jacqueline Jaqueline Janeth
Jasmín Jazmín Jenifer Jennifer Jenny Judith Julieth Justa Karen Katerine Katherine Kelly
Leidy Leonor Libia Lilian Linda Lisbeth Lizbeth Lizeth Lourdes Lucero Luna Luz Mabel Magaly
Maite Maribel Marisol Marleny Mary Matilde Mercedes Mery Mía Milagros Miriam Modesta Myriam
Nancy Natividad Nelly Nicole Noemí Nohemí Paloma Patria Paz Perla Piedad Pilar Prudencia
Raquel Remedios Rocío Rosa Rosario Rosmery Rubí Ruth Salomé Shirley Socorro Sol Soledad
Stephanie Trinidad Violeta Vivian Wendy Yamile Yaneth Yazmín Yeimy Yenny Yudy Yurany Yuri
Zoe Andrea Asunción América Ámbar Mariluz Marlene Mayerly Melany Nazaret Lilibeth Yuleisy
Ashley Brittany Cindy Darly Deyci Emily Geraldine Gissel Heidy Ivette Jackeline Jasmine
Joselyn Karol Katherin Kimberly Lesly Lisseth Madeleine Maryuri Michelle Mileidy Nataly Nikol
Sharon Sheyla Stefany Tiffany Yeimi Zharick Yulieth Yamileth Yudith Nelcy Nelsy Marleidy
Luzdary Ludy Magaly Mayra Yazmin Lucelly Fanny Gisell Jhoana Odalys Yohanna Yesica Ingrid
""")

M_OTHER = _words("""
Ángel Amado Domingo Santos Cruz Reyes Jesús Salvador León Pastor Modesto Justo Severo
Constante Benigno Bienvenido Plácido Feliz Rey Cristo Segundo Primitivo Próspero Fortunato
Inocencio Prudencio Celestino Leal Ulises Brayan Bryan Kevin John Johnny Jhonny Jimmy Fredy
Jeferson Yeferson Steven Estiven Michael Maikol Jeison Wilder Dylan Ian Liam Tiago Iker
Elián Sneider Deiby Dubán Faber Fáber Jhonatan Jonatan Yorman Álex Alex Alexis Ariel Denis
Farid Jamil Yamil Salim Noel René Israel Ezequías Herbert Ronald Richard William Edward
Alvaro Mathías Bautista Luca Nicola Andy Freddie Elkin
Andersson Arnold Brian Christian Cristhian Dilan Frank Leonard Óliver Oliver Patrick Robert
Walter Yeiner Yeisson Yhon Yorlan Jhoan Jhojan Edinson Jhonathan Yeffer Yeferson Brayhan
Duvan Jefferson Yordan Yeiler Wilmar Wilson Napoleón Máximo Cristiano Custodio Patrocinio
""")

# Names that do not tell gender on their own.
UNISEX = _words("Cris Dani Sasha Gabi Fran Charlie Jordan Robin Joan Alix")

# Compound given names whose gender is not the first token's (or worth pinning).
COMPOUND_GENDER = {
    "maria jose": "F", "jose maria": "M", "maria paz": "F", "jesus maria": "M",
    "maria de jesus": "F", "maria de los angeles": "F", "maria del mar": "F",
    "maria del pilar": "F", "maria del carmen": "F", "maria de la paz": "F",
    "maria del rosario": "F", "maria de la cruz": "F", "juan de dios": "M",
    "jose de jesus": "M", "ana maria": "F", "luz maria": "F", "rosa maria": "F",
    "maria angel": "F", "angel maria": "M", "maria auxiliadora": "F",
}

# Names that are common Spanish words, places or brands: lexicon yes, pools no.
WORDLIKE_GIVEN = set(_words("""
Rosa Luz Paz Sol Mar Flor Gloria Esperanza Mercedes Dolores Pilar Socorro Amparo Consuelo
Caridad Dulce Alma Linda Bella Mía Luna Blanca Perla Estrella Paloma Violeta Azucena
Camelia Hortensia Lourdes Guadalupe Fátima Francia Libia América Belén Concepción Asunción
Natividad Soledad Milagros Remedios Rosario Gracia Prudencia Clemencia Modesta Justa Amada
Patria Rubí Celeste Cielo Ámbar Victoria Ángel Amado Domingo Santos Cruz Reyes Jesús
Salvador León Pastor Modesto Justo Severo Constante Benigno Bienvenido Plácido Feliz Rey
Cristo Segundo Primitivo Próspero Fortunato Inocencio Prudencio Leal Franco Aurora
"""))

# Tokens that *are* given names but read as plain words when capitalized in running text.
# is_given_name() answers False for them so free-text detection does not fire on them.
NOT_A_NAME_IN_TEXT = set(_words("""
Domingo Bienvenido Bienvenida Justo Feliz Segundo Primitivo Modesto Leal Amado Amada
Pastor Rey Reina Cristo Salvador Santos Reyes Cruz Sol Mar América Francia Libia Patria
Alegría Azul Constante Severo Benigno Plácido Próspero Fortunato
"""))

# (first given name | first surname) pairs that would read as a public figure or a brand.
FAMOUS_PAIRS = {
    "sofia|vergara", "gabriel|garcia", "juan|valdez", "carlos|vives", "james|rodriguez",
    "nairo|quintana", "egan|bernal", "rigoberto|uran", "mariana|pajon", "caterine|ibarguen",
    "juan pablo|montoya", "fernando|botero", "gustavo|petro", "alvaro|uribe", "ivan|duque",
    "francia|marquez", "claudia|lopez", "sergio|fajardo", "federico|gutierrez",
    "rodolfo|hernandez", "cesar|gaviria", "andres|pastrana", "ernesto|samper", "pablo|escobar",
    "simon|bolivar", "antonio|narino", "jorge|gaitan", "jorge eliecer|gaitan",
    "luis carlos|galan", "carlos|valderrama", "rene|higuita", "faustino|asprilla",
    "radamel|garcia", "radamel|falcao", "teofilo|gutierrez", "juan manuel|santos",
    "belisario|betancur", "virgilio|barco", "alfonso|lopez", "carlos|lleras", "juan|cuadrado",
    "david|ospina", "luis|diaz", "fernando|vallejo", "hector|abad", "beatriz|gonzalez",
    "doris|salcedo", "debora|arango", "policarpa|salavarrieta", "carlos|gardel",
    "juan|gabriel", "salvador|dali", "pablo|neruda", "frida|kahlo", "gabriela|mistral",
    "jorge|isaacs", "jose|asuncion", "rafael|nunez", "manuel|elkin", "lucho|herrera",
    "luis|herrera", "martin|elias", "jorge|celedon", "diomedes|diaz", "joe|arroyo",
    "celia|cruz", "ruben|blades", "mario|bros", "paulina|rubio", "laura|pausini",
}
