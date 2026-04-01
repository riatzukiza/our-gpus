import type { LucideIcon } from 'lucide-react'

interface OverviewCard {
  label: string
  value: string
  detail: string
  icon: LucideIcon
}

interface OverviewGridProps {
  cards: OverviewCard[]
}

export default function OverviewGrid({ cards }: OverviewGridProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => {
        const Icon = card.icon
        return (
          <div key={card.label} className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">{card.label}</p>
                <p className="mt-2 text-2xl font-semibold capitalize text-gray-900 dark:text-white">{card.value}</p>
              </div>
              <div className="rounded-lg bg-blue-50 p-2 text-blue-600 dark:bg-blue-900/20 dark:text-blue-300">
                <Icon className="h-5 w-5" />
              </div>
            </div>
            <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">{card.detail}</p>
          </div>
        )
      })}
    </div>
  )
}
