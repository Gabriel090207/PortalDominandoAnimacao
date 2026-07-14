import {
  BookOpen,
  Bot,
  FileImage,
  FolderOpen,
  Home,
  LogOut,
  Search,
  Sparkles,
  Video,
  Volume2,
} from "lucide-react";

import { NavLink } from "react-router-dom";

import "./Sidebar.css";

const Sidebar = () => {
  return (
    <aside className="sidebar">
      <div className="sidebar__top">
        <div className="sidebar__brand">
          <div className="sidebar__logo">
            <Sparkles size={22} strokeWidth={2.2} />
          </div>

          <div className="sidebar__brand-text">
            <h2>
              <span>Dominando</span>
              <strong>Animação</strong>
            </h2>
          </div>
        </div>

        <div className="sidebar__search">
          <Search className="sidebar__search-icon" size={18} />

          <input
            type="text"
            placeholder="Buscar..."
          />
        </div>
      </div>

      <div className="sidebar__content">

        <nav className="sidebar__menu sidebar__menu--main">

         <NavLink
  to="/dashboard"
  className={({ isActive }) =>
    isActive
      ? "sidebar__item sidebar__item--active"
      : "sidebar__item"
  }
>
  <Home size={19} />

  <span>Início</span>
</NavLink>

        </nav>

        <div className="sidebar__section">

          <span className="sidebar__section-title">
            GERAR
          </span>

          <nav className="sidebar__menu">

            <NavLink
  to="/video"
  className={({ isActive }) =>
    isActive
      ? "sidebar__item sidebar__item--active"
      : "sidebar__item"
  }
>
              <Video size={14} />

              <span>Vídeo</span>
           </NavLink>

           <NavLink
  to="/voice"
  className={({ isActive }) =>
    isActive
      ? "sidebar__item sidebar__item--active"
      : "sidebar__item"
  }
>
  <Volume2 size={14} />

  <span>Voz</span>
</NavLink>

            <NavLink
  to="/image"
  className={({ isActive }) =>
    isActive
      ? "sidebar__item sidebar__item--active"
      : "sidebar__item"
  }
>
  <FileImage size={14} />

  <span>Imagem</span>
</NavLink>

           <NavLink
  to="/chat"
  className={({ isActive }) =>
    isActive
      ? "sidebar__item sidebar__item--active"
      : "sidebar__item"
  }
>
  <Bot size={14} />

  <span>Chat IA</span>
</NavLink>

            <NavLink
  to="/slides"
  className={({ isActive }) =>
    isActive
      ? "sidebar__item sidebar__item--active"
      : "sidebar__item"
  }
>
  <BookOpen size={14} />

  <span>Slides</span>
</NavLink>

          </nav>

        </div>

        <div className="sidebar__section">

          <span className="sidebar__section-title">
            BIBLIOTECA
          </span>

          <nav className="sidebar__menu">

          <NavLink
  to="/library"
  className={({ isActive }) =>
    isActive
      ? "sidebar__item sidebar__item--active"
      : "sidebar__item"
  }
>
  <FolderOpen size={14} />

  <span>Biblioteca</span>
</NavLink>
          </nav>

        </div>

      </div>

      <footer className="sidebar__footer">

        <div className="sidebar__profile">

          <div className="sidebar__avatar">
            GB
          </div>

          <div className="sidebar__user">
            <strong>Gabriel Borela</strong>

            <span>Plano Premium</span>
          </div>

          <button
            className="sidebar__logout"
            type="button"
          >
            <LogOut size={18} />
          </button>

        </div>

      </footer>

    </aside>
  );
};

export default Sidebar;