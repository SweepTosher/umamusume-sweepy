<template>
  <div class="card">
    <div class="card-body">
      <div class="portraits-header" @click="expanded = !expanded">
        <h5 class="mb-0">Friendship Levels<span class="portrait-count-badge" v-if="portraits.length">{{ portraits.length }}</span></h5>
        <span class="toggle-text">{{ expanded ? '▲' : '▼' }}</span>
      </div>
      <div v-if="expanded" class="portraits-body">
        <div v-if="portraits.length === 0" class="empty-state">No characters detected yet</div>
        <div v-else class="portraits-grid">
          <div v-for="p in portraits" :key="p.name" class="portrait-item" :class="{ 'portrait-npc': p.is_npc }">
            <div class="portrait-img-wrap">
              <img :src="'/training-icon/' + p.name" :alt="p.name" class="portrait-img" @error="onImgError">
            </div>
            <div class="portrait-name">{{ formatName(p.name) }}</div>
            <div class="portrait-type-badge" :class="p.is_npc ? 'badge-npc' : 'badge-deck'">{{ p.is_npc ? 'NPC' : 'Deck' }}</div>
            <div class="favor-bar">
              <div class="favor-pip" v-for="i in 4" :key="i" :class="{ filled: i <= p.favor, ['lv' + p.favor]: i <= p.favor }"></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: "DetectedPortraitsPanel",
  props: {
    portraits: { type: Array, default: () => [] }
  },
  data() {
    return { expanded: true }
  },
  methods: {
    formatName(n) {
      return n.replace(/_/g, ' ')
    },
    onImgError(e) {
      e.target.style.display = 'none'
    }
  }
}
</script>


