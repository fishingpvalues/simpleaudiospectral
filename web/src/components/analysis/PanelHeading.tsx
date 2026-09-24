import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

/** Small upper-case section title of the analysis panel. */
export function PanelHeading({ children, className = "mb-2" }: { children: ReactNode; className?: string }) {
  return (
    <h3 className={cn(className, "text-xs font-medium tracking-wide text-muted-foreground uppercase")}>{children}</h3>
  )
}
