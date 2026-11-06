import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import ChatterfyImportSource from '../src/components/ChatterfyImportSource'
import '../src/index.css'

function Fixture() {
  const [visible, setVisible] = useState(true)
  return <main className="mx-auto max-w-sm p-4 text-gray-100">
    <button onClick={() => setVisible(!visible)}>Toggle imported card</button>
    <ChatterfyImportSource customFields={visible ? { __chatterfy_import: {
      schema: 1, source_username: '<script>alert(1)</script>',
      campaign_id: '019f2c6d-dc0e-72ee-8792-3cc410f797f4', source_id: 'abcdefghijklmnopqrstuvwxyz012345678901234567890123456789',
    } } : {}} />
  </main>
}
createRoot(document.getElementById('root')!).render(<Fixture />)
