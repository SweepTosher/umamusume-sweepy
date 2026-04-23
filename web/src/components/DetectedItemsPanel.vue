<template>
  <div class="card">
    <div class="card-body">
      <div class="detected-items-header" @click="expanded = !expanded">
        <h5 class="mb-0">Owned Items <span class="item-count-badge" v-if="items.length">{{ items.length }}</span></h5>
        <span class="toggle-text">{{ expanded ? '▲' : '▼' }}</span>
      </div>
      <div v-if="expanded" class="detected-items-body">
        <div v-if="items.length === 0" class="empty-state">No items detected yet</div>
        <div v-else class="detected-items-list">
          <div v-for="item in sortedItems" :key="item.name" class="detected-item-row">
            <div class="item-info">
              <img v-if="getItemIcon(item.name)" :src="getItemIcon(item.name)" :alt="item.name" class="item-icon" />
              <span class="item-name">{{ item.name }}</span>
            </div>
            <span class="item-qty">×{{ item.qty }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
const iconModules = import.meta.glob('../assets/img/mant_items/*.png', { eager: true })

const iconMap = {}
for (const path in iconModules) {
  const filename = path.split('/').pop().replace('.png', '')
  iconMap[filename] = iconModules[path].default
}

function nameToSlug(displayName) {
  return displayName.toLowerCase().replace(/'/g, '').replace(/ /g, '_')
}

export default {
  name: "DetectedItemsPanel",
  props: {
    items: { type: Array, default: () => [] }
  },
  data() {
    return { expanded: true }
  },
  computed: {
    sortedItems() {
      return [...this.items].sort((a, b) => a.name.localeCompare(b.name))
    }
  },
  methods: {
    getItemIcon(name) {
      return iconMap[nameToSlug(name)] || null
    }
  }
}
</script>

