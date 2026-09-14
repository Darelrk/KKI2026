import { createRoot } from 'react-dom/client'
import { RemoteApp } from './app'
import './styles.css'

const backendOrigin = import.meta.env.VITE_REMOTE_BACKEND_ORIGIN || 'https://remote.monitor-kapal-pora-pora.web.id'
const asvId = import.meta.env.VITE_REMOTE_ASV_ID || 'default'

const root = document.getElementById('root')
if (!root) throw new Error('remote dashboard root is missing')

createRoot(root).render(<RemoteApp backendOrigin={backendOrigin} asvId={asvId} />)
