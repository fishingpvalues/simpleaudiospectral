import { Component, type ReactNode } from "react"

interface State { error: Error | null }

/** Keeps one failing panel from unmounting the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode; label: string }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.error(`[${this.props.label}]`, error)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" className="m-4 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
        <div className="font-medium text-destructive">{this.props.label} failed to render</div>
        <div className="mt-1 font-mono text-xs text-muted-foreground">{this.state.error.message}</div>
        <button className="mt-2 text-xs underline" onClick={() => this.setState({ error: null })}>Retry</button>
      </div>
    )
  }
}
