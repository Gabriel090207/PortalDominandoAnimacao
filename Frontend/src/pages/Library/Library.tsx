import {
  Bell,
  BookOpen,
  FileImage,
  FileText,
  Film,
  LibraryBig,
  Mic,
} from "lucide-react";

import Sidebar from "../../components/Sidebar/Sidebar";

import "./Library.css";

const Library = () => {
  return (
    <>
      <Sidebar />

      <main className="library-page">

        <header className="library-page__topbar">

          <div className="library-page__actions">

            <button
              className="library-page__status"
              type="button"
            />

            <button
              className="library-page__icon"
              type="button"
            >
              <Bell size={18} />
            </button>

          </div>

        </header>

        <section className="library-page__hero">

          <h1>Biblioteca</h1>

          <p>
            Tudo que você gerou, em um só lugar.
          </p>

        </section>

        <section className="library-filter">

          <button className="active">
            Tudo
          </button>

          <button>
            <Film size={16} />
            Vídeo
          </button>

          <button>
            <Mic size={16} />
            Voz
          </button>

          <button>
            <FileImage size={16} />
            Imagem
          </button>

          <button>
            <FileText size={16} />
            Texto
          </button>

          <button>
            <BookOpen size={16} />
            Slides
          </button>

        </section>

        <section className="library-empty">

          <div className="library-empty__icon">

            <LibraryBig size={34} />

          </div>

          <h2>
            Nada por aqui ainda
          </h2>

          <p>
            Suas gerações aparecerão nesta biblioteca.
          </p>

        </section>

      </main>
    </>
  );
};

export default Library;