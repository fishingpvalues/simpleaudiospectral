import * as React from "react"
import { Tooltip as TooltipPrimitive } from "radix-ui"
import { cn } from "@/lib/utils"
import { GLOSSARY, type Term as TermKey } from "@/lib/glossary"

const TooltipProvider = TooltipPrimitive.Provider
const Tooltip = TooltipPrimitive.Root
const TooltipTrigger = TooltipPrimitive.Trigger

function TooltipContent({
  className,
  sideOffset = 6,
  children,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        sideOffset={sideOffset}
        className={cn(
          "z-50 animate-in rounded-md bg-primary px-2 py-1 text-xs text-primary-foreground fade-in-0 zoom-in-95",
          className,
        )}
        {...props}
      >
        {children}
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  )
}

/** Icon button with a tooltip - the toolbar is almost entirely made of these. */
function Tip({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  // Icon-only buttons get their tooltip text as accessible name, so a screen
  // reader announces "Zoom in (+)" rather than "button".
  const child =
    typeof label === "string" &&
    React.isValidElement<{ "aria-label"?: string }>(children) &&
    !children.props["aria-label"]
      ? React.cloneElement(children, { "aria-label": label })
      : children
  return (
    <Tooltip>
      <TooltipTrigger asChild>{child}</TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

/** A label with a glossary explanation on hover and keyboard focus. */
function Term({ term, children, className }: { term: TermKey; children: React.ReactNode; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline cursor-help bg-transparent p-0 text-left font-[inherit] text-inherit underline decoration-muted-foreground/40 decoration-dotted underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
            className,
          )}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-left leading-snug">{GLOSSARY[term]}</TooltipContent>
    </Tooltip>
  )
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider, Tip, Term }
