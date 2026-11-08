import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import LoginPage from '../src/pages/LoginPage'
import '../src/index.css'

function Destination() {
  const location = useLocation()
  return <output>{location.pathname + location.search}</output>
}
const query = new URLSearchParams(window.location.search)
createRoot(document.getElementById('root')!).render(<MemoryRouter initialEntries={[
  { pathname: '/login', state: { from: { pathname: query.get('from'), search: query.get('search') } } },
]}><Routes><Route path="/login" element={<LoginPage />} /><Route path="/settings" element={<Destination />} /><Route path="/chats" element={<Destination />} /></Routes></MemoryRouter>)
