<script lang="ts">
// Named exports that consumers can import from this SFC.
export interface FetchPageParams {
  startRow: number
  endRow: number
  blockSize: number
  sortModel: { colId: string; sort: 'asc' | 'desc' }[]
  filterModel: Record<string, unknown>
  cursor: string | null
}
export interface FetchPageResult<R> {
  rows: R[]
  nextCursor?: string | null
  lastRow?: number
}
export default {}
</script>

<script setup lang="ts" generic="T extends Record<string, unknown>">
import { ref, shallowRef, computed, onBeforeUnmount } from 'vue'
import { AgGridVue } from 'ag-grid-vue3'
import {
  ModuleRegistry,
  AllCommunityModule,
  themeQuartz,
  type ColDef,
  type GridApi,
  type GridReadyEvent,
  type IDatasource,
  type IGetRowsParams,
  type GetRowIdParams,
} from 'ag-grid-community'

ModuleRegistry.registerModules([AllCommunityModule])


const props = withDefaults(
  defineProps<{
    columns: ColDef[]
    fetchPage: (p: FetchPageParams) => Promise<FetchPageResult<T>>
    getRowId?: (row: T) => string
    blockSize?: number
    rowHeight?: number
  }>(),
  { blockSize: 100, rowHeight: 40 },
)

const emit = defineEmits<{ (e: 'row-click', row: T): void }>()

// Dark theme matching the Vuestic palette / App.vue :root vars.
const theme = themeQuartz.withParams({
  backgroundColor: '#1a1d27',
  foregroundColor: '#e2e8f0',
  chromeBackgroundColor: '#22263a',
  headerBackgroundColor: '#22263a',
  borderColor: '#2e3354',
  accentColor: '#6366f1',
  rowHoverColor: '#22263a',
  fontSize: 13,
})

const gridApi = shallowRef<GridApi | null>(null)
// cursor cache: maps a block's startRow -> the cursor needed to fetch it.
const cursors = new Map<number, string | null>()

const datasource: IDatasource = {
  getRows: async (params: IGetRowsParams) => {
    try {
      const res = await props.fetchPage({
        startRow: params.startRow,
        endRow: params.endRow,
        blockSize: props.blockSize,
        sortModel: params.sortModel as { colId: string; sort: 'asc' | 'desc' }[],
        filterModel: params.filterModel,
        cursor: cursors.get(params.startRow) ?? null,
      })
      if (res.nextCursor !== undefined) cursors.set(params.endRow, res.nextCursor)
      const lastRow =
        res.lastRow ??
        (res.rows.length < props.blockSize ? params.startRow + res.rows.length : undefined)
      params.successCallback(res.rows as Record<string, unknown>[], lastRow)
    } catch {
      params.failCallback()
    }
  },
}

const defaultColDef = ref<ColDef>({ sortable: true, resizable: true, flex: 1, minWidth: 100 })

// Move getRowId wrapper to script to avoid inline TS in template
const getRowIdFn = computed(() => {
  if (!props.getRowId) return undefined
  return (p: GetRowIdParams<T>) => props.getRowId!(p.data)
})

function onGridReady(e: GridReadyEvent) {
  gridApi.value = e.api
  e.api.setGridOption('datasource', datasource)
}
function onRowClicked(e: { data?: T }) {
  if (e.data) emit('row-click', e.data)
}

function refresh() {
  cursors.clear()
  gridApi.value?.purgeInfiniteCache()
}
defineExpose({ refresh })

onBeforeUnmount(() => { gridApi.value = null })
</script>

<template>
  <AgGridVue
    class="data-grid"
    :theme="theme"
    :columnDefs="columns"
    :defaultColDef="defaultColDef"
    :rowModelType="'infinite'"
    :cacheBlockSize="blockSize"
    :rowHeight="rowHeight"
    :getRowId="getRowIdFn"
    @grid-ready="onGridReady"
    @row-clicked="onRowClicked"
  />
</template>

<style scoped>
.data-grid { width: 100%; height: 100%; min-height: 420px; }
</style>
