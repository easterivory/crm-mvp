"""Conservative name extraction for funnel answers, not profile or manual edits."""

import re
import unicodedata
from pathlib import Path


def name_key(value: str) -> str:
    value = value.translate(str.maketrans({"’": "'", "ʻ": "'", "‘": "'", "ʼ": "'"}))
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(c)).replace("ё", "е")


# Recognition hints, not an exhaustive whitelist of legitimate names.
KNOWN_NAMES = frozenset(name_key(name) for name in """
Александр Александра Алексей Алёна Алина Анастасия Андрей Анна Антон Артём
Артемий Артур Борис Валентина Валерий Валерия Василий Вера Виктор Виктория
Виталий Владимир Владислав Галина Георгий Григорий Даниил Дарья Денис Дмитрий
Евгений Евгения Екатерина Елена Елизавета Иван Игорь Илья Ирина Кирилл Ксения
Константин Лев Леонид Любовь Людмила Максим Маргарита Марина Мария Михаил
Надежда Наталья Никита Николай Олег Ольга Павел Пётр Полина Роман Руслан Светлана
Семён Сергей София Станислав Степан Татьяна Тимофей Тимур Фёдор Юлия Юрий Яна
Саша Маша Даша Лена Катя Настя Миша Дима Ваня Серёжа Женя Лёша
Aziz Азиз Aziza Азиза Alisher Алишер Anvar Анвар Akmal Акмаль Akmaljon Акмалжон
Abror Аброр Asad Асад Behzod Бехзод Bekzod Бекзод Bobur Бобур Davron Даврон
Baxtiyor Bahtiyor Bakhtiyor Бахтиёр Бахтиер Бахтиор Бахтияр Baxtiyar Bakhtiyar
Baxti Bahti Bakhti Бахти
Dilshod Дилшод Dilorom Дилором Dilnoza Дилноза Durdona Дурдона Farrukh Фаррух
Farhod Фарход Firdavs Фирдавс Gulnora Гульнора Gulnoza Гульноза Islom Ислом
Jamshid Жамшид Jasur Жасур Javohir Жавохир Kamola Камола Laziz Лазиз
Lola Лола Madina Мадина Malika Малика Maftuna Мафтуна Muhammad Мухаммад
Mohira Мохира Murod Мурод Nodir Нодир Nodira Нодира Nigora Нигора
Nargiza Наргиза Nurbek Нурбек Otabek Отабек Oybek Ойбек Ozod Озод
Rustam Рустам Ravshan Равшан Sardor Сардор Sanjar Санжар Sarvar Сарвар
Said Саид Saida Саида Shahzod Шахзод Shohruh Шохрух Sherzod Шерзод
Shavkat Шавкат Sevara Севара Shaxnoza Шахноза Umid Умид Ulugbek Улугбек
Zafar Зафар Zilola Зилола Ziyoda Зиёда Zulfiya Зульфия
Abigail Adriana Alejandro Alejandra Alberto Alfredo Ana Andrés Andrea Antonio
Beatriz Bruno Camila Carlos Carmen Carolina Catalina Cecilia Cristian Cristina
Daniel Daniela David Diego Eduardo Elena Enrique Esteban Fabián Felipe Fernanda
Fernando Francisco Gabriela Gabriel Gonzalo Gustavo Héctor Hugo Ignacio Isabel
Isabella Javier Jesús Jimena Joaquín Jorge José Juan Juana Juliana Julio Julia
Laura Leonardo Leticia Lorena Lucas Lucía Luciano Luis Luisa Manuel Manuela
María Mariana Mario Martín Mateo Matías Melissa Mercedes Miguel Natalia Nicolás
Óscar Pablo Patricia Paula Pedro Rafael Raquel Ricardo Roberto Rocío Rodrigo
Rosa Rubén Salvador Samuel Santiago Sebastián Sergio Silvia Sofía Teresa Tomás
Valentina Valeria Verónica Vicente Víctor Ximena Yolanda
João José Antônio Luiz Luís Júlia Vitória Vinícius Joãozinha Thiago Tiago
Letícia Márcia Cláudia Patrícia Fábio Márcio Afonso André
Авдей Адам Адриан Аким Алан Альберт Альбина Амир Амина Анатолий Ангелина
Анжелика Антонина Арина Аркадий Арсений Богдан Вадим Вениамин Вероника
Виолетта Всеволод Вячеслав Геннадий Герман Глеб Гордей Давид Демид Демьян
Диана Дина Ева Евдокия Егор Елисей Есения Захар Зинаида Злата Инга Инна
Иосиф Кира Клим Кристина Лариса Лидия Лилия Майя Макар Марк Матвей Милана
Милена Мирон Мирослава Назар Нина Нонна Оксана Платон Прохор Раиса Регина
Ренат Ринат Рита Роберт Родион Ростислав Рустем Савелий Савва Серафим
Снежана Тамара Таисия Тихон Ульяна Филипп Эдуард Эльвира Элина Эмиль
Эмилия Юлиана Яков Ярослав Ярослава
Саня Санёк Сашенька Сашуля Сашка Шура Шурик Алекс Лёха Лёшенька Алёша
Андрюша Андрюха Андрюх Антоша Антоха Артёмка Тёма Тёмка Артурик Боря
Валя Валюша Валера Валерик Вася Васенька Васька Витя Витюша Виталик
Вова Вовка Вовчик Володя Володька Влад Владик Владя Слава Славик Галя
Галочка Гена Генка Гоша Гриша Гришка Даня Данила Данилка Ден Дениска
Димка Димон Димочка Митя Митенька Женька Женечка Женёк Катюша Катенька
Катерина Катюня Леночка Ленчик Лиза Лизочка Егорка Ванечка Ванька Игорёк
Илюша Илюха Илюшка Ира Ирочка Иришка Кирюша Кирюха Костя Костик Ксюша
Ксюшенька Ксюха Лёва Лёвушка Лёня Лёнька Люба Любаша Люда Людочка Люся
Макс Максик Марго Маришка Маруся Машенька Машуля Машка Мишка Мишаня Михалыч
Надя Надюша Наташа Наташенька Ната Ник Никитка Коля Коленька Колян Олежка
Оля Оленька Паша Павлик Пашка Петя Петенька Поля Полечка Рома Ромка Ромчик
Русик Русланчик Света Светик Светочка Сеня Сёма Семёнка Серёга Серёжка
Серж Соня Сонечка Стас Стасик Стёпа Стёпка Таня Танюша Танечка Тим Тимка
Тимоша Тима Федя Феденька Филиппка Юля Юленька Юляша Юра Юрка Юрик Яша
Ларочка Лара Лида Лидочка Лиля Лилечка Зина Зиночка Зоя Зоечка Тоня
Тося Нюра Нюша Аня Анюта Анютка Анечка Настька Настюша Настенька Стеша
Уля Улечка Тася Тая Тамара Тома Томочка Рая Раечка Диночка Дианочка
Sasha Sanya Shura Shurik Alex Aleksandr Alexandr Aleksander Alexander
Aleksandra Alexandra Alexey Aleksey Aleksei Alexei Alyosha Lesha Lyosha
Andrey Andrei Andrei Anton Artyom Artem Artiom Artyomka Tema Tyoma
Vladimir Volodya Vova Vladislav Vlad Vyacheslav Slava Sergey Sergei Sergej
Serezha Seryozha Serega Seryoga Dmitry Dmitriy Dmitri Dimitri Dima Dimon
Mikhail Mikhayl Misha Ivan Vanya Nikolay Nikolai Kolya Konstantin Kostya
Evgeniy Evgeny Evgeni Yevgeniy Zhenya Yuri Yuriy Yury Yura Ilya Ilia
Pavel Pasha Pyotr Petr Petya Fyodor Fedor Fedya Roman Roma Oleg Ruslan
Nikita Kirill Kiryl Timur Timofey Maksim Maxim Max Daniil Danil Danila
Yaroslav Yaroslaw Yasha Yakov Boris Borya Grigory Grigoriy Grisha Gleb
Anna Anya Ania Anyuta Anastasia Anastasiya Anastasiia Nastya Nastia
Ekaterina Yekaterina Katerina Katya Katia Katyusha Elena Yelena Lena
Elizaveta Liza Lizaveta Irina Ira Iryna Ksenia Kseniya Kseniia Ksyusha
Olga Olya Natalia Natalya Nataliya Natasha Nadezhda Nadya Nadiya
Yulia Yuliya Yuliia Yulya Julija Svetlana Sveta Tatyana Tatiana Tanya
Lyudmila Ludmila Lyuda Liudmila Lyubov Lubov Lyuba Galina Galya
Viktoria Viktoriya Vika Veronika Alina Alyona Alena Oksana Polina Polya
Mariya Masha Darya Daria Dasha Sofiya Sofiia Sonya Sonia Yana Yanina
Абдулла Abdulla Abdullah Абдулло Абдулазиз Abdulaziz Abdul Azizbek Азизбек
Абдурахмон Абдурахман Abdurahmon Abdurakhmon Abdurahman Абдурашид Abdurashid
Абдусамад Abdusamad Абдували Abduvali Абдувохид Abduvohid Абдукадир Abduqodir
Акмал Akmalbek Акмалбек Алишержон Alisherjon Анваржон Anvarjon Асадбек Asadbek
Аваз Avaz Аъзам Azam Азамат Azamat Азим Azim Азимжон Azimjon
Бахром Bahrom Bakhrom Baxrom Бахриддин Bahriddin Бек Behruz Бехруз Беҳруз
Бунёд Bunyod Буниёд Bunyodbek Бунёдбек Ботир Botir Батыр Batyr
Далер Daler Достон Doston Дилшодбек Dilshodbek Дилшоджон Dilshodjon
Дониёр Дониер Doniyor Doniyer Довуд Dovud Элдор Eldor Элёр Elyor
Элмурод Elmurod Эркин Erkin Фазлиддин Fazliddin Феруз Feruz
Фаррук Farruh Farukh Фарҳод Farxod Фируз Firuz Ғайрат Gʻayrat Gayrat G'ayrat
Гайрат Ғиёс Gʻiyos Giyos G'iyos Хамид Hamid Ҳамид Хасан Hasan Ҳасан
Хусейн Husayn Huseyn Хусен Husen Ҳусайн Хусан Husan Ҳусан
Хикмат Hikmat Ҳикмат Хуршид Хуршидбек Xurshid Khurshid Hurshid Xurshidbek
Иброхим Иброҳим Ibrohim Ibrahim Икром Ikrom Илхом Илҳом Ilhom Ilkhom
Илхомжон Ilhomjon Искандар Iskandar Исломбек Islombek Исмоил Ismoil Ismail
Иззат Izzat Иззатбек Izzatbek Жахонгир Жаҳонгир Jahongir Jakhongir
Жахон Jahon Жамол Jamol Жамшидбек Jamshidbek Жасурбек Jasurbek
Жавоҳир Javoxir Javokhir Камол Kamol Камолиддин Kamoliddin Комил Komil
Қодир Кодир Qodir Kodir Лочин Lochin Лутфулло Lutfullo
Мансур Mansur Масуд Masud Махмуд Маҳмуд Mahmud Makhmud
Мирза Mirza Мирзохид Mirzohid Миржалол Mirjalol Миршод Mirshod
Мирзабек Mirzabek Мирзохид Mirzohid Мухаммаджон Muhammadjon
Мухаммадали Muhammadali Мухаммадюсуф Muhammadyusuf Мухаммадзиё Muhammadziyo
Мухаммадбек Muhammadbek Мухаммадсодик Muhammadsodiq Мухаммадрасул Muhammadrasul
Муҳаммад Мухамед Muhamed Muhammed Mohammed Мухаммадшариф Muhammadsharif
Музаффар Muzaffar Мурат Murat Муроджон Murodjon Нодирбек Nodirbek
Нозим Nozim Нуриддин Nuriddin Нурислом Nurislom Нурмухаммад Nurmuhammad
Олим Olim Олимжон Olimjon Ориф Orif Отабекжон Otabekjon Ойбекжон Oybekjon
Ота Ota Полат Poʻlat Po'lat Polat Пўлат Пулат Pulat Қахрамон Qahramon
Кахрамон Қаҳрамон Кудрат Қудрат Qudrat Kudrat Рахим Rahim
Рамз Ramz Рамзиддин Ramziddin Расул Rasul Рашид Rashid Равшанбек Ravshanbek
Рустамбек Rustambek Саидбек Saidbek Сайид Sayid Салохиддин Salohiddin
Салохиддин Салахиддин Salahiddin Самандар Samandar Самад Samad
Санжарбек Sanjarbek Сардорбек Sardorbek Сарварбек Sarvarbek Сухроб Suhrob Sukhrob
Шахзод Shaxzod Шоҳзод Shoxzod Shohzod Шахзодбек Shahzodbek
Шохруҳ Шоҳруҳ Шохрух Shohrux Shoxrux Shohruh Shahrukh
Шерзодбек Sherzodbek Шер Sher Шерзоджон Sherzodjon Шерзод Sherzod
Шерзодбек Шухрат Shuhrat Shukhrat Шуҳрат Шухроб Shuhrob
Шукрулло Shukrullo Темур Temur Тоҳир Тохир Tohir Тохиржон Tohirjon
Турсуной Tursunoy Улугбек Ulugʻbek Ulug'bek Улуғбек Умиджон Umidjon
Усмон Usmon Uthmon Уткир Ўткир Oʻtkir O'tkir Otkir Utkir
Уткирбек Otkirbek Хожи Xoji Хожиакбар Xojiakbar Хожи Акбар Akbar
Хусанбой Husanboy Ҳусанбой Хусниддин Husniddin Зафарбек Zafarbek
Зиёд Ziyod Зокир Zokir Зохид Zohid Зоҳид Зухриддин Zuhriddin Юсуф Yusuf
Юсуп Yusup Юсуфбек Yusufbek Яхё Yahyo Яҳё Яшин Yashin
Асал Asal Асила Asila Аслия Asliya Алия Aliya Барно Barno
Бахора Bahora Баҳора Чарос Charos Дилбар Dilbar Дилдора Dildora
Дилафруз Dilafruz Дилфуза Dilfuza Дилрабо Dilrabo Дилнавоз Dilnavoz
Дилнура Dilnura Дилноз Dilnoz Дилдора Dildora Фарангиз Farangiz
Феруза Feruza Фируза Firuza Фотима Fotima Fatima Гавхар Gavhar Гавҳар
Гулбахор Gulbahor Гулбаҳор Гульбахор Гулчехра Gulchehra Гулчеҳра
Гулмира Gulmira Гулноз Gulnoz Гулнора Gulnora Гулрух Gulruh Gulrux
Гулсанам Gulsanam Гулшода Gulshoda Гузал Goʻzal Go'zal Gozal Гўзал
Хадича Xadicha Khadicha Ҳадича Халима Halima Ҳалима Хилола Hilola Ҳилола
Хуршида Xurshida Khurshida Ҳуршида Ирода Iroda Интизор Intizor
Кумуш Kumush Латофат Latofat Лайло Laylo Лейла Leyla Лобар Lobar
Мавлюда Mavluda Mavlyuda Мавлуда Махлиё Mahliyo Маҳлиё Махфуза Mahfuza
Муниса Munisa Мунира Munira Муштарий Mushtariy Мухлиса Muxlisa Mukhlisa
Муқаддас Мукаддас Muqaddas Мухаббат Muhabbat Муҳаббат Насиба Nasiba
Нафиса Nafisa Назокат Nazokat Наргис Nargis Нозима Nozima Нозли Nozli
Нозанин Nozanin Нозигул Nozigul Нилуфар Nilufar Нигора Nigora Нигина Nigina
Озода Ozoda Одиля Odila Одила Ойдин Oydin Ойгул Oygul Ойша Oysha Aisha
Ойшахон Oyshaxon Паризода Parizoda Райхон Rayhon Райҳон Рано Ra'no Rano Раъно
Рухшона Ruxshona Ruhshona Рушана Rushana Сабина Sabina Сабохат Sabohat
Садаф Sadaf Саодат Saodat Севарахон Sevaraxon Ситора Sitora
Шахло Shahlo Shaxlo Шаҳло Шахноза Shahnoza Шаҳноза
Шоира Shoira Шохиста Shoxista Shohista Шаҳзода Shahzoda Shaxzoda
Тахмина Tahmina Тамила Tamila Умида Umida Угилой Oʻgʻiloy O'g'iloy Ўғилой
Зарина Zarina Зебо Zebo Зулфия Zulfiya Зухра Zuhra Zukhra Зуҳра
Aaron Abel Adán Agustín Alan Alexis Alonso Álvaro Amalia Amanda Amparo
Ángel Ángela Ángeles Angélica Anahí Ariana Ariadna Aurora Axel Bárbara
Benjamín Berenice Bianca Brenda Bryan Brayan César Clara Claudio Claudia
Cintia Cynthia Damián Darío Débora Diana Dolores Domingo Dulce Edgar Edgardo
Efraín Elías Elisa Eloísa Elsa Elvira Emiliano Emilio Emilia Emma Emmanuel
Erick Erik Erika Ernesto Esperanza Ezequiel Facundo Federico Félix
Florencia Florinda Franco Franklin Gerardo Germán Gina Gloria Graciela
Guadalupe Guillermo Iliana Inés Ingrid Irma Ismael Iván Ivana Jacqueline
Jacobo Jaime Jairo Janeth Janet Jazmín Jennifer Jéssica Jessica Johana
Johanna Jonathan Jonatan Josué Judith Karen Karina Kiara Kevin Leandro
Lidia Liliana Lizbeth Lourdes Luciana Luz Magalí Magdalena Maribel Marisol
Martha Marta Mauro Maximiliano Melina Micaela Mónica Nancy Naomi Noelia
Norma Octavio Omar Orlando Osvaldo Paloma Paola Pamela Priscila Ramiro
Raúl Rebeca Regina Renata Renato Reynaldo Romina Ronaldo Rosana Rosario
Roxana Ruth Sabrina Sandra Saúl Selene Silvana Susana Tadeo Tatiana
Teodoro Trinidad Ulises Vanessa Violeta Virginia Walter Wendy William
Yamila Yasmín Yesenia Yésica Yuliana Zaira Zoe Zoé
Ale Alex Alejo Alexia Alejandrina Nacho Nachito Paco Pancho Pacho Panchito
Pepe Pepito Chepe Josefa Josefina Chema Joselito Josecito Chuy Chucho Toño
Tonio Tony Toni Anto Tono Manolo Manu Lucho Luisito Luismi Lupe Lupita
Chava Santi Sebas Seba Basti Bastian Sebastián Sebita Sebi Nico Nicolás
Nicolás Nicky Mati Maty Matías Mateo Teo Fede Fefi Fer Nando Ferni
Gabi Gaby Gabri Gabriel Gabriela Dani Daniel Danilo Dany Danny Dan
Juanito Juancho Juani Juancito Juanca Juanma Juampi Juampy Juana Juanita
Pablito Pablo Pao Pau Paulina Paulita Pauli Carlitos Carli Charly Charlie
Carito Caro Carolina Carola Cami Camilo Camila Cata Catalina Caterina
Marce Marcelo Marcela Marcel Mariela Mari Maru Marita Maricarmen Maricela
Mariángel Mariangel María-José Maria-Jose Ana-María Ana-Maria Ana-Paula
Majo Majito Mafer Marifer Marijo Marisol Marisa Marisela Maritza
Vero Verito Vane Vani Val Vale Valen Valeria Valentina Tina Tini
Nati Naty Nat Natalia Natacha Sole Solange Soledad
Sofi Sofy Sofía Sofie Sofie Sofía Roci Rocío Ro Roque Rocio
Lore Lorena Loli Lolita Lola Lalo Lalito Beto Betito Tavo Gustavo Gus
Rafa Rafi Rafael Rapha Raúl Raulito Rulo Ruli Roberto Rob Robi Robert
Rober Robe Robertito Bobby Bob Rodri Rodrigo Rorro Rigo Ricardo Richi
Ricky Riki Richard Rick Diego Dieguito Diegui Didi Eduardo Edu Edi Eddie
Edú Enrique Quique Kike Quico Fran Francis Francisco Francisca Francy
Franco Franchesca Francesca Esteban Estefi Estefanía Estefania Stefi
Tere Teresita Teresa Ceci Cecilia Chechu Celia Celi Celeste
Javi Javier Javiera Javito Jime Jimena Xime Ximena Agus Agustina Agustín
Florencia Flori Floppy Feli Felipe Felisa Félix Meli Melisa Melissa
Melu Luli Luciana Lucila Lucía Lu Luci Lucie Lucita Lulú Lulu
Patri Patricia Patricio Pato Patty Paty Pili Pilar Pilarica
Belén Belen Belu Belén Beba Betty Bety Beatriz Bea Bia Betty
Adri Adrián Adriana Adriano Andre Andy Andrés Andrea Andi Andreíta
Iza Isa Isabel Isabela Isabella Isaías Sabel Chabela Chabelita
Juli Juliana Julieta Julia Julito Julián Julian Juliano
Ângelo Aparecida Aparecido Ariane Artur Augusto Benedito Bruna Caio Cauã
Cleiton Cristiano Davi Denilson Douglas Edson Eliane Eliana Emanuel
Ester Evandro Fabiana Fabrício Flávia Flávio Geovana Giovanna Giovana
Geraldo Gilberto Gilmar Guilherme Henrique Heloísa Helena Iara Igor
Isadora Jéssica Kauã Larissa Laís Lais Leila Lívia Luciane Lucimar
Luana Luan Luiza Luciene Marcio Marcos Marlon Matheus Mateus Mayara
Michel Mirella Murilo Natália Otávio Pedro Pietro Rafael Rafaela Raissa
Rayssa Robson Rogério Rosângela Rubens Silvio Simone Sueli Tainá Taís
Talita Thais Thaís Thalita Thales Vagner Valdir Vanderlei Vânia Vitor
Wagner Wallace Washington Wellington Wesley Wilian Wilson Yago Yasmin
Zé Zezinho Zeca Zezé Joãozinho Joaozinho Joãozito Joca Jô Jôjo
Gui Guiga Guigui Dudu Duduzinho Cadu Kadu Kaká Kaka Duda Dudinha
Rafinha Rafa Paulinho Pedrinho Juninho Júnior Junior Bruninho Bruninha
Nandinho Nandinha Fernandinha Fernandinho Fê Fe Luizinho Luisinho Luquinhas
Luizão Marcão Marquinhos Marquinho Claudinho Claudinha Rê Rezinha
Beto Betinho Robertinho Ricardinho Rodrigo Rodriguinho Diguinho
Léo Leo Leozinho Leandro Lê Leninha Lene Aninha Aninha Ana Clara Clarinha
Carol Carô Carlinha Cá Cacá Carlinhos Carolzinha Carlinha Mari Marizinha
Mariana Marianinha Má Maju Malu Maria-Luiza Maria-Eduarda Maria-Clara
Gabi Gabizinha Gabs Guga Gustavo Gustavinho Gu Gui Vini Vinícius Vinicius
Vitinho Vítor Vitor Vi Vivi Vivian Viviane Vivi Vitória Vitoria
Tati Tatiane Tata Taty Dani Daniele Danielle Daniela Dany Daniella
Juju Ju Juh Julinha Juju Júlio Julinho Julinha Juçara
Lari Larissa Lalá Lala Letícia Lê Lele Lelê Babi Barbara Bá
Naná Nana Nanda Nati Nathália Nathalia Nath Natália Nat Isa Iza
Bel Bela Belinha Bia Beatriz Bibi Bebel Beta Bel Betina Bettina
Rô Rosi Rose Roseli Rosana Rosângela Rosangela Rosi Rosinha
Mi Mimi Mila Milena Camila Camilinha Mica Mika Rafa Rafinha Raquel
""".split())

KNOWN_NAMES = KNOWN_NAMES | frozenset(
    name_key(name) for name in
    (Path(__file__).resolve().parents[1] / "data/given_names/names.txt").read_text(encoding="utf-8").splitlines()
)

_WORD = r"[^\W\d_]+(?:[-'’ʻ‘ʼ][^\W\d_]+)*"
_TOKEN = re.compile(_WORD, re.UNICODE)
_CUE = re.compile(
    r"(?:\bменя\s+зовут|\bмо[её]\s+имя|\bимя|\bфио|\bme\s+llamo|"
    r"\bmi\s+nombre\s+es|\bmeu\s+nome\s+[ée]|\bismim|\bmening\s+ismim)\s*[:\-]?\s*",
    re.IGNORECASE,
)
_STOP = frozenset(name_key(word) for word in """
привет здравствуйте добрый день вечер утро спасибо да нет не знаю мне лет из живу город
хорошо понятно отлично нормально ладно ок okay ok bien gracias saludos listo
работаю опыта опыт хочу начать зовут имя я меня мой моя это зовут тест админ
hola buenas buenos dias tardes gracias no se tengo anos soy de vivo ciudad trabajo
quiero empezar mi nombre es y e olá bom boa obrigado tenho sou moro em anos
salom yosh yoshdaman men ismim rahmat bilmayman test admin user unknown
рустили рус тили русча узбекча ўзбекча билмайман билмаймен тушунмайман
rus tili ruscha uzbekcha oʻzbekcha tushunmayman
""".split())
_PARTICLES = {"de", "del", "da", "do", "dos", "das", "la", "los"}


def extract_answer_name(text: str) -> str | None:
    """Extract a name span; competing candidates ask for clarification instead."""
    text = unicodedata.normalize("NFC", text).strip()
    if not text or len(text) > 16000:
        return None
    text = re.sub(r"https?://\S+|\S*@\S+", " ", text)
    cues = list(_CUE.finditer(text))
    candidates: list[str] = []
    segments = [text[cue.end():].splitlines()[0] for cue in cues if text[cue.end():].strip()] if cues else re.split(r"[\n,;.!?:]+", text)
    for segment in segments:
        tokens = list(_TOKEN.finditer(segment))
        start = next((i for i, token in enumerate(tokens)
                      if name_key(token.group()) in KNOWN_NAMES), None)
        if cues:
            start = 0 if tokens else None
            if start is not None and segment[:tokens[0].start()].strip():
                continue
        if start is None:
            # Accept a rare standalone name, but not arbitrary multiword prose.
            clean = segment.strip()
            if len(segments) == 1 and _TOKEN.fullmatch(clean) and name_key(clean) not in _STOP:
                if clean[0].isupper() and 2 <= len(clean) <= 50 and not re.search(r"(.)\1{3}", clean.casefold()):
                    candidates.append(clean)
            continue
        selected: list[str] = []
        previous_end = tokens[start].start()
        for token in tokens[start:]:
            word = token.group()
            key = name_key(word)
            gap = segment[previous_end:token.start()]
            if gap.strip() or len(selected) >= 6 or len(word) > 50:
                break
            if re.search(r"(.)\1{3}", word.casefold()):
                break
            if key in _STOP and key not in _PARTICLES:
                break
            # Lowercase unknown words in prose cannot safely be treated as surnames.
            if selected and key not in KNOWN_NAMES and key not in _PARTICLES and not word[0].isupper():
                break
            if key in _PARTICLES and (not selected or token == tokens[-1]):
                break
            selected.append(word)
            previous_end = token.end()
        while selected and name_key(selected[-1]) in _PARTICLES:
            selected.pop()
        if selected and len(selected[0]) >= 2:
            candidates.append(" ".join(selected))
    unique = {name_key(candidate): candidate for candidate in candidates}
    return next(iter(unique.values())) if len(unique) == 1 else None
