<template>
  <div class="card">
    <div class="card-body">
      <div class="detected-skills-header" @click="expanded = !expanded">
        <h5 class="mb-0">Detected Skills <span class="skill-count-badge" v-if="skills.length">{{ skills.length }}</span></h5>
        <span class="toggle-text">{{ expanded ? '▲' : '▼' }}</span>
      </div>
      <div v-if="expanded" class="detected-skills-body">
        <div v-if="skills.length === 0" class="empty-state">No skills detected yet</div>
        <div v-else class="detected-skills-list">
          <div v-for="skill in sortedSkills" :key="skill.name" class="detected-skill-row" :class="{ gold: skill.gold }">
            <div class="skill-info">
              <span class="skill-name">{{ skill.name }}</span>
              <span v-if="skill.cost > 0" class="skill-cost">{{ skill.cost }}pt</span>
            </div>
            <div class="skill-meta">
              <span v-if="skill.hint_level > 0" class="hint-tag">Lv{{ skill.hint_level }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: "DetectedSkillsPanel",
  props: {
    skills: { type: Array, default: () => [] }
  },
  data() {
    return { expanded: true }
  },
  computed: {
    sortedSkills() {
      return [...this.skills].sort((a, b) => {
        if (a.gold !== b.gold) return a.gold ? -1 : 1
        if (a.hint_level !== b.hint_level) return b.hint_level - a.hint_level
        return a.name.localeCompare(b.name)
      })
    }
  }
}
</script>

