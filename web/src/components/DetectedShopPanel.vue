<template>
  <div class="card">
    <div class="card-body">
      <div class="shop-header" @click="expanded = !expanded">
        <h5 class="mb-0">Shop Items <span class="item-count-badge" v-if="items.length">{{ items.length }}</span></h5>
        <span class="toggle-text">{{ expanded ? '▲' : '▼' }}</span>
      </div>
      <div v-if="expanded" class="shop-body">
        <div v-if="items.length === 0" class="empty-state">No shop items detected yet</div>
        <div v-else class="shop-list">
          <div
            v-for="item in sortedItems"
            :key="item.name"
            class="shop-item-row"
            :class="{ purchased: item.purchased }"
          >
            <div class="item-info">
              <img v-if="getItemIcon(item.name)" :src="getItemIcon(item.name)" :alt="item.name" class="item-icon" />
              <span class="item-name">{{ item.name }}</span>
            </div>
            <div class="item-meta">
              <span v-if="item.turns < 99" class="turns-badge">{{ item.turns }}T</span>
              <span v-if="item.purchased" class="purchased-badge">Bought</span>
            </div>
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

function nameToSlug(name) {
  return name.toLowerCase().replace(/'/g, '').replace(/ /g, '_')
}

export default {
  name: "DetectedShopPanel",
  props: {
    items: { type: Array, default: () => [] }
  },
  data() {
    return { expanded: true }
  },
  computed: {
    sortedItems() {
      return [...this.items].sort((a, b) => {
        const ta = a.turns < 99 ? a.turns : 999
        const tb = b.turns < 99 ? b.turns : 999
        if (ta !== tb) return ta - tb
        return a.name.localeCompare(b.name)
      })
    }
  },
  methods: {
    getItemIcon(name) {
      return iconMap[nameToSlug(name)] || null
    }
  }
}
</script>

