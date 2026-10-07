import { useState } from 'react'
import {
  Bell,
  ChevronDown,
  ChevronRight,
  Menu,
  Plus,
  Search,
  X,
} from 'lucide-react'
import {
  activity,
  metrics,
  navigation,
  secondaryNavigation,
  tasks,
  workstreams,
} from './data'

function App() {
  const [activeItem, setActiveItem] = useState('Overview')
  const [menuOpen, setMenuOpen] = useState(false)

  const selectNavigation = (label: string) => {
    setActiveItem(label)
    setMenuOpen(false)
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${menuOpen ? 'sidebar--open' : ''}`}>
        <div className="brand">
          <div className="brand__mark" aria-hidden="true">
            N
          </div>
          <div>
            <strong>Northstar</strong>
            <span>Project delivery</span>
          </div>
        </div>

        <button
          className="icon-button sidebar__close"
          type="button"
          aria-label="Close navigation"
          onClick={() => setMenuOpen(false)}
        >
          <X size={20} />
        </button>

        <nav className="nav" aria-label="Main navigation">
          <span className="nav__label">Workspace</span>
          {navigation.map(({ label, icon: Icon }) => (
            <button
              className={`nav__item ${activeItem === label ? 'nav__item--active' : ''}`}
              type="button"
              key={label}
              onClick={() => selectNavigation(label)}
            >
              <Icon size={19} strokeWidth={1.8} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <nav className="nav nav--secondary" aria-label="Secondary navigation">
          {secondaryNavigation.map(({ label, icon: Icon }) => (
            <button
              className={`nav__item ${activeItem === label ? 'nav__item--active' : ''}`}
              type="button"
              key={label}
              onClick={() => selectNavigation(label)}
            >
              <Icon size={19} strokeWidth={1.8} />
              <span>{label}</span>
            </button>
          ))}
          <div className="profile">
            <div className="avatar avatar--profile">RK</div>
            <div className="profile__copy">
              <strong>Rohan Kapoor</strong>
              <span>Program manager</span>
            </div>
            <ChevronDown size={16} />
          </div>
        </nav>
      </aside>

      {menuOpen && (
        <button
          className="sidebar-backdrop"
          aria-label="Dismiss navigation"
          onClick={() => setMenuOpen(false)}
        />
      )}

      <main className="main">
        <header className="topbar">
          <button
            className="icon-button menu-button"
            type="button"
            aria-label="Open navigation"
            onClick={() => setMenuOpen(true)}
          >
            <Menu size={20} />
          </button>

          <label className="search">
            <Search size={18} />
            <span className="sr-only">Search</span>
            <input placeholder="Search projects, tasks, or people" />
            <kbd>/</kbd>
          </label>

          <button className="icon-button notification-button" type="button" aria-label="Notifications">
            <Bell size={19} />
            <span className="notification-dot" />
          </button>
        </header>

        <div className="content">
          <section className="page-heading">
            <div>
              <p>Wednesday, 7 October</p>
              <h1>Good afternoon, Rohan</h1>
              <span>Here is how the transformation program is moving.</span>
            </div>
            <button className="primary-button" type="button">
              <Plus size={18} />
              New task
            </button>
          </section>

          <section className="metrics" aria-label="Project summary">
            {metrics.map((metric) => (
              <article className="metric" key={metric.label}>
                <div className={`metric__accent metric__accent--${metric.tone}`} />
                <span>{metric.label}</span>
                <strong>{metric.value}</strong>
                <small>{metric.detail}</small>
              </article>
            ))}
          </section>

          <div className="dashboard-grid">
            <section className="panel panel--workstreams">
              <div className="panel__header">
                <div>
                  <h2>Workstream progress</h2>
                  <p>Delivery health across active workstreams</p>
                </div>
                <button className="text-button" type="button">
                  View all <ChevronRight size={16} />
                </button>
              </div>

              <div className="workstream-list">
                {workstreams.map((workstream) => (
                  <article className="workstream" key={workstream.name}>
                    <div className="workstream__identity">
                      <div className="avatar">{workstream.initials}</div>
                      <div>
                        <h3>{workstream.name}</h3>
                        <span>{workstream.owner}</span>
                      </div>
                    </div>
                    <div className="workstream__progress">
                      <div className="progress-meta">
                        <span>{workstream.tasks}</span>
                        <strong>{workstream.progress}%</strong>
                      </div>
                      <div
                        className="progress-track"
                        role="progressbar"
                        aria-label={`${workstream.name} progress`}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={workstream.progress}
                      >
                        <span style={{ width: `${workstream.progress}%` }} />
                      </div>
                    </div>
                    <span
                      className={`status ${workstream.status === 'At risk' ? 'status--risk' : ''}`}
                    >
                      {workstream.status}
                    </span>
                  </article>
                ))}
              </div>
            </section>

            <section className="panel">
              <div className="panel__header">
                <div>
                  <h2>Upcoming</h2>
                  <p>Tasks assigned to you</p>
                </div>
                <button className="icon-button" type="button" aria-label="View all tasks">
                  <ChevronRight size={18} />
                </button>
              </div>

              <div className="task-list">
                {tasks.map((task) => (
                  <button className="task" type="button" key={task.title}>
                    <span className="task__check" aria-hidden="true" />
                    <span className="task__copy">
                      <strong>{task.title}</strong>
                      <small>{task.meta}</small>
                    </span>
                    <span className={task.urgent ? 'date date--urgent' : 'date'}>
                      {task.date}
                    </span>
                  </button>
                ))}
              </div>
            </section>

            <section className="panel panel--activity">
              <div className="panel__header">
                <div>
                  <h2>Recent activity</h2>
                  <p>Latest changes across the program</p>
                </div>
              </div>
              <div className="activity-list">
                {activity.map(({ icon: Icon, title, detail, time }) => (
                  <article className="activity" key={title}>
                    <div className="activity__icon">
                      <Icon size={17} />
                    </div>
                    <div>
                      <strong>{title}</strong>
                      <span>{detail}</span>
                    </div>
                    <time>{time}</time>
                  </article>
                ))}
              </div>
            </section>
          </div>
        </div>
      </main>
    </div>
  )
}

export default App
