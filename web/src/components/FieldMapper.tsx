import { ArrowRight } from 'lucide-react'

interface FieldMapperProps {
  schema: {
    fields: Record<string, string>
    sample_records: any[]
  }
  mapping: Record<string, string>
  onMappingChange: (mapping: Record<string, string>) => void
}

const targetFields = [
  { name: 'ip', label: 'IP Address', required: true },
  { name: 'port', label: 'Port', required: false },
  { name: 'geo_country', label: 'Country', required: false },
  { name: 'geo_city', label: 'City', required: false },
  { name: 'tags', label: 'Tags', required: false }
]

export default function FieldMapper({ schema, mapping, onMappingChange }: FieldMapperProps) {
  const handleChange = (targetField: string, sourceField: string) => {
    const newMapping = { ...mapping }
    if (sourceField) {
      newMapping[targetField] = sourceField
    } else {
      delete newMapping[targetField]
    }
    onMappingChange(newMapping)
  }
  
  return (
    <div className="mt-6">
      <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Field Mapping</h3>
      
      <div className="space-y-3">
        {targetFields.map(field => (
          <div key={field.name} className="flex items-center space-x-4">
            <div className="w-1/3">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                {field.label}
                {field.required && <span className="text-red-500 ml-1">*</span>}
              </label>
            </div>
            
            <ArrowRight className="w-5 h-5 text-gray-400 dark:text-gray-500" />
            
            <div className="flex-1">
              <select
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={mapping[field.name] || ''}
                onChange={(e) => handleChange(field.name, e.target.value)}
              >
                <option value="">-- Select source field --</option>
                {Object.keys(schema.fields).map(sourceField => (
                  <option key={sourceField} value={sourceField}>
                    {sourceField} ({schema.fields[sourceField]})
                  </option>
                ))}
              </select>
            </div>
          </div>
        ))}
      </div>
      
      <div className="mt-6 p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
        <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Sample Record Preview</h4>
        {schema.sample_records[0] && (
          <pre className="text-xs text-gray-600 dark:text-gray-300 overflow-x-auto">
            {JSON.stringify(schema.sample_records[0], null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}