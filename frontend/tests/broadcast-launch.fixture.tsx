import { createRoot } from 'react-dom/client'
import BroadcastWizard from '../src/features/broadcasts/components/BroadcastWizard'
import { emptyAudienceFilter, type Broadcast } from '../src/features/broadcasts/types'
import '../src/index.css'

const draft: Broadcast = {
  id: 'qa-draft', project_id: 'qa-project', bot_id: 'qa-bot', name: 'Local launch test',
  content_json: { type: 'message', messages: [{ type: 'text', text: 'Local preview only' }] },
  audience_filter_json: emptyAudienceFilter(), audience_count: 0, status: 'draft',
  schedule_type: 'now', scheduled_at: null, timezone_mode: 'project', is_deleted: false,
  created_by_user_id: null, created_at: '', updated_at: '', sent_at: null,
}
createRoot(document.getElementById('root')!).render(<main className="h-screen p-3">
  <BroadcastWizard broadcast={draft} projectId="qa-project" defaultBotId="qa-bot"
    bots={[{ id: 'qa-bot', label: 'QA bot' }]} tags={[]} statuses={[]} trackingLinks={[]}
    users={[]} funnels={[]} templates={[]} snippets={[]} chatFilterPresets={[]}
    onSaveTemplate={async () => {}} onUploadMedia={async () => { throw new Error('Not used') }}
    onBack={() => {}} onSaved={() => {}} />
</main>)
