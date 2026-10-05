"use client";
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";

/* ---------------------------------------------------------------- Button */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-violet disabled:pointer-events-none disabled:opacity-40",
  {
    variants: {
      variant: {
        primary: "bg-violet text-ink hover:bg-violet/85",
        outline: "border border-ink-400 bg-transparent text-paper hover:bg-ink-600",
        ghost: "text-paper-dim hover:bg-ink-600 hover:text-paper",
        verify: "border border-emerald-line bg-emerald-soft text-emerald hover:bg-emerald/20",
        review: "border border-amber-line bg-amber-soft text-amber hover:bg-amber/20",
        danger: "border border-danger-line bg-danger-soft text-danger hover:bg-danger/20",
        data: "border border-cyan-line bg-cyan-soft text-cyan hover:bg-cyan/20",
      },
      size: { sm: "h-7 px-2.5 text-xs", md: "h-8 px-3 text-sm", icon: "h-7 w-7" },
    },
    defaultVariants: { variant: "outline", size: "md" },
  },
);
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> { asChild?: boolean; loading?: boolean }
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild, loading, children, disabled, ...props }, ref) => {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} disabled={disabled || loading} {...props}>
      {asChild ? children : (<>{loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}{children}</>)}
    </Comp>
  );
});
Button.displayName = "Button";

/* ---------------------------------------------------------------- Inputs */
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input ref={ref} className={cn("h-8 w-full rounded border border-ink-400 bg-ink-800 px-2.5 text-sm text-paper placeholder:text-paper-faint focus:border-violet focus:outline-none", className)} {...props} />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn("w-full rounded border border-ink-400 bg-ink-800 px-2.5 py-2 text-sm text-paper placeholder:text-paper-faint focus:border-violet focus:outline-none", className)} {...props} />
));
Textarea.displayName = "Textarea";

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(({ className, children, ...props }, ref) => (
  <select ref={ref} className={cn("h-8 rounded border border-ink-400 bg-ink-800 px-2 text-sm text-paper focus:border-violet focus:outline-none", className)} {...props}>{children}</select>
));
Select.displayName = "Select";

/* ---------------------------------------------------------------- Badge */
const badgeVariants = cva("inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 font-mono text-2xs uppercase tracking-wider", {
  variants: {
    tone: {
      neutral: "border-ink-400 bg-ink-600 text-paper-dim",
      violet: "border-violet-line bg-violet-soft text-violet",
      cyan: "border-cyan-line bg-cyan-soft text-cyan",
      emerald: "border-emerald-line bg-emerald-soft text-emerald",
      amber: "border-amber-line bg-amber-soft text-amber",
      danger: "border-danger-line bg-danger-soft text-danger",
      magenta: "border-magenta-line bg-magenta-soft text-magenta",
    },
  },
  defaultVariants: { tone: "neutral" },
});
export type Tone = NonNullable<VariantProps<typeof badgeVariants>["tone"]>;
export function Badge({ className, tone, ...props }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

/* ---------------------------------------------------------------- Panel */
export function Panel({ className, children, ...props }: React.HTMLAttributes<HTMLElement>) {
  return <section className={cn("rounded-md border border-ink-500/80 bg-ink-800/90", className)} {...props}>{children}</section>;
}
export function PanelHeader({ title, icon, right, tone = "neutral", className }: { title: React.ReactNode; icon?: React.ReactNode; right?: React.ReactNode; tone?: Tone; className?: string }) {
  const bar: Record<Tone, string> = { neutral: "bg-ink-400", violet: "bg-violet", cyan: "bg-cyan", emerald: "bg-emerald", amber: "bg-amber", danger: "bg-danger", magenta: "bg-magenta" };
  return (
    <header className={cn("flex items-center justify-between gap-3 border-b border-ink-500/80 px-3.5 py-2", className)}>
      <div className="flex items-center gap-2">
        <span className={cn("h-3 w-[3px] rounded-full", bar[tone])} />
        {icon && <span className="text-paper-mute">{icon}</span>}
        <h2 className="label-micro !text-paper-dim">{title}</h2>
      </div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </header>
  );
}

/* ---------------------------------------------------------------- Tabs */
export const Tabs = TabsPrimitive.Root;
export const TabsList = React.forwardRef<React.ElementRef<typeof TabsPrimitive.List>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>>(({ className, ...p }, ref) => (
  <TabsPrimitive.List ref={ref} className={cn("flex items-center gap-1 border-b border-ink-500/80", className)} {...p} />
));
TabsList.displayName = "TabsList";
export const TabsTrigger = React.forwardRef<React.ElementRef<typeof TabsPrimitive.Trigger>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>>(({ className, ...p }, ref) => (
  <TabsPrimitive.Trigger ref={ref} className={cn("-mb-px border-b-2 border-transparent px-3 py-2 font-mono text-2xs uppercase tracking-[0.12em] text-paper-mute transition-colors hover:text-paper data-[state=active]:border-violet data-[state=active]:text-paper", className)} {...p} />
));
TabsTrigger.displayName = "TabsTrigger";
export const TabsContent = TabsPrimitive.Content;

/* ---------------------------------------------------------------- Dialog */
export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
export function DialogContent({ className, children, title, description, ...props }: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & { title: string; description?: string }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/70 backdrop-blur-[2px]" />
      <DialogPrimitive.Content className={cn("fixed left-1/2 top-1/2 z-50 max-h-[88vh] w-[min(92vw,720px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-md border border-ink-400 bg-ink-800 shadow-2xl focus:outline-none", className)} {...props}>
        <div className="flex items-start justify-between border-b border-ink-500 px-4 py-3">
          <div>
            <DialogPrimitive.Title className="text-sm font-semibold text-paper">{title}</DialogPrimitive.Title>
            {description ? <DialogPrimitive.Description className="mt-0.5 text-xs text-paper-mute">{description}</DialogPrimitive.Description> : <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>}
          </div>
          <DialogPrimitive.Close className="rounded p-1 text-paper-mute hover:bg-ink-600 hover:text-paper" aria-label="Close"><X className="h-4 w-4" /></DialogPrimitive.Close>
        </div>
        <div className="p-4">{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

/* ---------------------------------------------------------------- Switch */
export const Switch = React.forwardRef<React.ElementRef<typeof SwitchPrimitive.Root>, React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>>(({ className, ...p }, ref) => (
  <SwitchPrimitive.Root ref={ref} className={cn("relative h-4 w-8 shrink-0 rounded-full border border-ink-400 bg-ink-600 transition-colors data-[state=checked]:border-emerald-line data-[state=checked]:bg-emerald/30", className)} {...p}>
    <SwitchPrimitive.Thumb className="block h-3 w-3 translate-x-0.5 rounded-full bg-paper-mute transition-transform data-[state=checked]:translate-x-[17px] data-[state=checked]:bg-emerald" />
  </SwitchPrimitive.Root>
));
Switch.displayName = "Switch";

/* ---------------------------------------------------------------- Misc */
export function Spinner({ className }: { className?: string }) { return <Loader2 className={cn("h-4 w-4 animate-spin text-paper-mute", className)} />; }

export function EmptyState({ icon, title, hint, action }: { icon?: React.ReactNode; title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      {icon && <div className="text-paper-faint">{icon}</div>}
      <p className="text-sm font-medium text-paper-dim">{title}</p>
      {hint && <p className="max-w-md text-xs text-paper-mute">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="rounded border border-danger-line bg-danger-soft px-3 py-2 text-xs text-danger" role="alert">{message}</div>;
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="rounded-sm border border-ink-400 bg-ink-600 px-1 font-mono text-2xs text-paper-dim">{children}</kbd>;
}
