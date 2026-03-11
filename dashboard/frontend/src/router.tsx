import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppLayout } from './layouts/AppLayout'
import App from './App'

const PlaceholderView = ({ name }: { name: string }) => (
  <div style={{ padding: '2rem', color: 'var(--text)', fontFamily: 'var(--font)' }}>
    {name} view — coming soon
  </div>
)

export const router = createBrowserRouter(
  [
    {
      path: '/app',
      element: <AppLayout />,
      children: [
        { index: true, element: <Navigate to="inbox" replace /> },
        { path: 'inbox', element: <App /> },
        { path: 'inbox/:source', element: <App /> },
        { path: 'tasks', element: <PlaceholderView name="Tasks" /> },
        { path: 'jira', element: <PlaceholderView name="Jira Sprint" /> },
        { path: 'calendar', element: <PlaceholderView name="Calendar" /> },
        { path: 'daily', element: <PlaceholderView name="Daily Log" /> },
        { path: 'learnings', element: <PlaceholderView name="Learnings" /> },
        { path: 'knowledge', element: <PlaceholderView name="Knowledge" /> },
        { path: 'suggestions', element: <PlaceholderView name="Suggestions" /> },
        { path: 'playbooks', element: <PlaceholderView name="Playbooks" /> },
      ],
    },
  ],
  { basename: '/' },
)
