const fs = require('fs');
const path = require('path');

const publicAssetsDir = path.join(__dirname, '..', 'public', 'assets');

if (fs.existsSync(publicAssetsDir)) {
    const files = fs.readdirSync(publicAssetsDir);
    files.forEach(file => {
        if (file.match(/^index\..*\.(js|css)$/)) {
            const fullPath = path.join(publicAssetsDir, file);
            if (fs.existsSync(fullPath)) {
                try {
                    fs.unlinkSync(fullPath);
                } catch (e) {
                    console.warn(`Failed to delete ${fullPath}: ${e.message}`);
                }
            }
        }
    });
}
