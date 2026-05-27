import "../styles/Auth.css";

const sections = [
  {
    title: "Administrator danych",
    body: [
      "[UZUPELNIJ: pelna nazwa administratora, adres siedziby, NIP/KRS jezeli dotyczy].",
      "Kontakt w sprawach prywatnosci: [UZUPELNIJ: adres e-mail lub formularz kontaktowy].",
    ],
  },
  {
    title: "Jakie dane przetwarzamy",
    body: [
      "Dane konta: nazwa uzytkownika, adres e-mail, hash hasla, rola konta i daty techniczne.",
      "Dane dokumentow: nazwy plikow, typy plikow, tresc dokumentow przeslanych do analizy ESG, chunki, embeddingi oraz wyniki raportow.",
      "Dane techniczne: adres IP, identyfikatory zadan, logi bledow, informacje o wykorzystaniu endpointow i rate limitach.",
    ],
  },
  {
    title: "Cele i podstawy przetwarzania",
    body: [
      "Utworzenie i obsluga konta, autoryzacja oraz bezpieczenstwo uslugi: [UZUPELNIJ: podstawa prawna, np. art. 6 ust. 1 lit. b/f RODO].",
      "Analiza dokumentow ESG, generowanie raportow, walidacja standardow i eksport PDF: [UZUPELNIJ: podstawa prawna].",
      "Kontakt z uzytkownikiem i obsluga zgloszen: [UZUPELNIJ: podstawa prawna].",
      "Ochrona przed naduzyciami, botami i atakami, w tym rate limity: [UZUPELNIJ: prawnie uzasadniony interes administratora].",
    ],
  },
  {
    title: "Odbiorcy danych i transfer",
    body: [
      "Dane moga byc przetwarzane przez dostawcow infrastruktury, bazy danych, kolejek zadan, monitoringu oraz modeli AI.",
      "[UZUPELNIJ: lista kategorii odbiorcow, nazwy kluczowych dostawcow, informacja o transferach poza EOG oraz zabezpieczeniach, np. SCC].",
    ],
  },
  {
    title: "Retencja i usuwanie danych",
    body: [
      "Dokumenty zrodlowe sa przechowywane tak dlugo, jak uzytkownik chce korzystac z nich do RAG, raportow i walidacji.",
      "Uzytkownik moze uzyc akcji finalizacji, ktora usuwa dokumenty zrodlowe, chunki i zapisane dowody z raportow. Wygenerowany JSON raportu pozostaje w historii do osobnego usuniecia.",
      "[UZUPELNIJ: docelowe okresy retencji kont, raportow, logow technicznych i zgloszen kontaktowych].",
    ],
  },
  {
    title: "Prawa uzytkownika",
    body: [
      "Uzytkownik moze zadac dostepu do danych, sprostowania, usuniecia, ograniczenia przetwarzania, przeniesienia danych oraz wniesienia sprzeciwu, jezeli wynika to z RODO.",
      "Uzytkownik ma prawo wniesc skarge do Prezesa Urzedu Ochrony Danych Osobowych.",
      "[UZUPELNIJ: procedura skladania zadan i dane kontaktowe].",
    ],
  },
  {
    title: "AI i automatyzacja",
    body: [
      "Platforma wykorzystuje modele AI do ekstrakcji, generowania raportow i walidacji zgodnosci. Wyniki powinny byc sprawdzane przez uzytkownika przed uzyciem biznesowym lub prawnym.",
      "[UZUPELNIJ: czy wystepuje zautomatyzowane podejmowanie decyzji w rozumieniu RODO art. 22; domyslnie raporty nie powinny samodzielnie wywolywac skutkow prawnych].",
    ],
  },
  {
    title: "Bezpieczenstwo",
    body: [
      "Backend wymaga JWT, sprawdza wlasciciela zasobow, ogranicza rozmiar uploadu, sprzata pliki tymczasowe i stosuje rate limity.",
      "Nie nalezy przesylac danych, ktorych administrator nie ma prawa przetwarzac w usludze.",
    ],
  },
];

export default function PrivacyPolicy() {
  return (
    <div className="auth-container privacy-page">
      <header className="topbar">
        <div className="brand">
          E<span>S</span>G
        </div>
        <nav className="nav">
          <a href="/">Home</a>
          <a href="/login">Login</a>
          <a href="/contact">Contact us</a>
        </nav>
      </header>

      <main className="privacy-content">
        <section className="privacy-hero">
          <h1>Polityka prywatnosci</h1>
          <p>
            Szablon informacyjny RODO dla platformy ESG. Pola oznaczone jako
            [UZUPELNIJ] wymagaja uzupelnienia przez administratora danych przed
            publikacja produkcyjna.
          </p>
        </section>

        <div className="privacy-sections">
          {sections.map((section) => (
            <section className="privacy-section" key={section.title}>
              <h2>{section.title}</h2>
              {section.body.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </section>
          ))}
        </div>
      </main>
    </div>
  );
}
