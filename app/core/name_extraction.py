"""Conservative name extraction for funnel answers, not profile or manual edits."""

import re
import unicodedata


def name_key(value: str) -> str:
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
""".split())

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
