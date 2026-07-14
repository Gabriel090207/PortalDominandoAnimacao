import {
  Video,
  Volume2,
  FileImage,
  Bot,
  BookOpen,
  FolderOpen,
} from "lucide-react";

import { NavLink } from "react-router-dom";

import "./BottomNavigation.css";

const BottomNavigation = () => {
  return (
    <nav className="bottom-nav">

      <NavLink to="/video" className="bottom-nav__item">
        <Video size={22} />
        <span>Vídeo</span>
      </NavLink>

      <NavLink to="/voice" className="bottom-nav__item">
        <Volume2 size={22} />
        <span>Voz</span>
      </NavLink>

      <NavLink to="/image" className="bottom-nav__item">
        <FileImage size={22} />
        <span>Imagem</span>
      </NavLink>

      <NavLink to="/chat" className="bottom-nav__item">
        <Bot size={22} />
        <span>Chat</span>
      </NavLink>

      <NavLink to="/slides" className="bottom-nav__item">
        <BookOpen size={22} />
        <span>Slides</span>
      </NavLink>

      <NavLink to="/library" className="bottom-nav__item">
        <FolderOpen size={22} />
        <span>Biblioteca</span>
      </NavLink>

    </nav>
  );
};

export default BottomNavigation;