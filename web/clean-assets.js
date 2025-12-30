const fs = require('fs');
const path = require('path');

// Clean old JS and CSS files from public/assets
const publicAssetsDir = path.join(__dirname, '..', 'public', 'assets');

if (fs.existsSync(publicAssetsDir)) {
    const files = fs.readdirSync(publicAssetsDir);
    let cleanedCount = 0;
    
    files.forEach(file => {
        if (file.match(/^index\..*\.(js|css)$/)) {
            fs.unlinkSync(path.join(publicAssetsDir, file));
            cleanedCount++;
            console.log(`🗑️ Removed: ${file}`);
        }
    });
    
    if (cleanedCount > 0) {
        console.log(`✅ Cleaned ${cleanedCount} old files`);
    } else {
        console.log(`ℹ️ No old files to clean`);
    }
} else {
    console.log(`ℹ️ public/assets directory doesn't exist yet`);
} 